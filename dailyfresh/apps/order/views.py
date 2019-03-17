from django.shortcuts import render, redirect
from django.core.urlresolvers import reverse
from django.views.generic import View
from django.http import JsonResponse
from django.db import transaction

from django_redis import get_redis_connection

from goods.models import GoodsSKU
from user.models import Address
from order.models import OrderInfo, OrderGoods

from datetime import datetime

from utils.mixin import LoginRequiredMixin
# Create your views here.


# /order/place
class OrderPlaceView(LoginRequiredMixin, View):
    '''提交订单页面显示'''
    def post(self, request):
        '''提交订单页面显示'''
        # 获取登录用户
        user = request.user
        # 获取sku_id参数
        sku_ids = request.POST.getlist('sku_ids')
        # 校验参数
        # if not sku_ids:
        #     # 跳转到购物车页面
        #     return redirect(reverse('cart:show'))
        conn = get_redis_connection('default')
        cart_id = 'cart_%d'%user.id

        # 业务处理,遍历sku_ids获取用户要购买购买商品的信息
        skus = []
        # 保存总数量和总价格
        total_count = 0
        total_price = 0
        for sku_id in sku_ids:
            sku = GoodsSKU.objects.get(id=sku_id)
            # 获取用户购买的商品数量
            count = conn.hget(cart_id, sku_id)
            # 计算商品的小计
            amount = sku.price * int(count)
            # 动态给sku添加属性
            sku.amount = amount
            sku.count = count
            skus.append(sku)
            total_price += amount
            total_count += int(count)

        # 运费
        transit_price = 10
        # 实付款
        total_pay = total_price + transit_price

        # 获取用户地址
        addrs = Address.objects.filter(user=user)

        # 组织上下文
        sku_ids = ','.join(sku_ids)
        context = {
            'addrs': addrs,
            'skus': skus,
            'total_count': total_count,
            'total_price': total_price,
            'transit_price': transit_price,
            'total_pay': total_pay,
            'sku_ids': sku_ids
        }
        # 返回应答
        return render(request, 'place_order.html', context)


# 前端传递的参数：地址id(addr_id), 支付方式(pay_method),用户要购买的商品id字符串(sku_ids)
# pessimistic lock
class OrderCommitView1(View):
    '''订单创建'''
    @transaction.atomic
    def post(self,request):
        '''订单创建'''
        # 判断用户是否登录
        user = request.user
        if not user.is_authenticated():
            # 用户未登录
            return JsonResponse({'res':0, 'errmsg': '用户未登录'})

        # 接收参数
        addr_id = request.POST.get('addr_id')
        pay_method = request.POST.get('pay_method')
        sku_ids = request.POST.get('sku_ids')

        # 校验参数
        if not all([addr_id, pay_method, sku_ids]):
            return JsonResponse({'res': 1, 'errmsg': '参数不完整'})

        # 校验支付方式
        if pay_method not in OrderInfo.PAY_METHOD.keys():
            return JsonResponse({'res': 2, 'errmsg': '非法的支付方式'})

        # 校验地址
        try:
            addr = Address.objects.get(id= addr_id)
        except Address.DoesNotExist:
            return JsonResponse({'res': 3, 'errmsg':'地址不正确'})

        # todo:创建订单核心业务

        # 组织参数
        # 订单id
        order_id = datetime.now().strftime('%Y%m%d%H%M%S')+str(user.id)

        # 运费
        transit_price = 10

        # 总数目和总金额
        total_count =0
        total_price =0

        # 设置保存点
        save_id = transaction.savepoint()
        try:
            # todo: 向order_info添加一条记录
            order = OrderInfo.objects.create(order_id=order_id,
                                             user=user,
                                             addr=addr,
                                             pay_method=pay_method,
                                             total_count=total_count,
                                             total_price=total_price,
                                             transit_price=transit_price)
            # todo: 用户订单中有几个商品，向OrderGoods中添加记录
            conn = get_redis_connection('defalut')
            cart_key = 'cart_%d'%user.id
            sku_ids = sku_ids.split(',')
            for sku_id in sku_ids:
                try:
                    # select * from df_goods_sku_where id = sku_id for update;
                    sku = GoodsSKU.objects.select_for_update().get(id=sku_id)
                except GoodsSKU.DoesNotExist:
                    # 商品不存在
                    transaction.savepoint_rollback(save_id)
                    return JsonResponse({'res': 4, 'errmsg': '商品不存在'})
                # 从redis获取用户购物车商品数量
                count = conn.hget(cart_key, sku_id)

                # todo: 判断商品库存
                if int(count) > sku.stock:
                    transaction.savepoint_rollback(save_id)
                    return ({'res': 6, 'errmsg':'库存不足'})
                price = sku.price

                # todo:添加记录
                OrderGoods.objects.create(order=order,
                                          sku=sku,
                                          count=count,
                                          price=price)

                # todo: 更新商品的库存和销量
                sku.stock -= int(count)
                sku.sales += int(count)
                sku.save()

                # todo: 计算订单商品的总金额和总数量
                amount = sku.price*int(count)
                total_price += amount
                total_count += int(count)

            # todo: 更新订单信息表中的商品总数量和总价格
            order.total_count = total_count
            order.total_price = total_price
            order.save()
        except Exception as e:
            transaction.savepoint_rollback(save_id)
            return JsonResponse({'res':7, 'errmsg': '下单失败'})
        # 提交事务
        transaction.savepoint_commit(save_id)

        # todo: 清除用户购物车中对应的记录
        conn.hdel(cart_key, *sku_ids)

        return JsonResponse({'res':5, 'message': '创建成功'})


# optimistic lock
class OrderCommitView(View):
    '''订单创建'''
    @transaction.atomic
    def post(self,request):
        '''订单创建'''
        # 判断用户是否登录
        user = request.user
        if not user.is_authenticated():
            # 用户未登录
            return JsonResponse({'res':0, 'errmsg': '用户未登录'})

        # 接收参数
        addr_id = request.POST.get('addr_id')
        pay_method = request.POST.get('pay_method')
        sku_ids = request.POST.get('sku_ids')

        # 校验参数
        if not all([addr_id, pay_method, sku_ids]):
            return JsonResponse({'res': 1, 'errmsg': '参数不完整'})

        # 校验支付方式
        if pay_method not in OrderInfo.PAY_METHOD.keys():
            return JsonResponse({'res': 2, 'errmsg': '非法的支付方式'})

        # 校验地址
        try:
            addr = Address.objects.get(id= addr_id)
        except Address.DoesNotExist:
            return JsonResponse({'res': 3, 'errmsg':'地址不正确'})

        # todo:创建订单核心业务

        # 组织参数
        # 订单id
        order_id = datetime.now().strftime('%Y%m%d%H%M%S')+str(user.id)

        # 运费
        transit_price = 10

        # 总数目和总金额
        total_count =0
        total_price =0

        # 设置保存点
        save_id = transaction.savepoint()
        try:
            # todo: 向order_info添加一条记录
            order = OrderInfo.objects.create(order_id=order_id,
                                             user=user,
                                             addr=addr,
                                             pay_method=pay_method,
                                             total_count=total_count,
                                             total_price=total_price,
                                             transit_price=transit_price)
            # todo: 用户订单中有几个商品，向OrderGoods中添加记录
            conn = get_redis_connection('defalut')
            cart_key = 'cart_%d'%user.id
            sku_ids = sku_ids.split(',')
            for sku_id in sku_ids:
                for i in range(3):
                    try:
                        # select * from df_goods_sku_where id = sku_id for update;
                        sku = GoodsSKU.objects.get(id=sku_id)
                    except GoodsSKU.DoesNotExist:
                        # 商品不存在
                        transaction.savepoint_rollback(save_id)
                        return JsonResponse({'res': 4, 'errmsg': '商品不存在'})
                    # 从redis获取用户购物车商品数量
                    count = conn.hget(cart_key, sku_id)

                    # todo: 判断商品库存
                    if int(count) > sku.stock:
                        transaction.savepoint_rollback(save_id)
                        return ({'res': 6, 'errmsg':'库存不足'})
                    price = sku.price

                    # todo: 更新商品的库存和销量
                    # sku.stock -= int(count)
                    # sku.sales += int(count)
                    # sku.save()
                    origin_stock = sku.stock
                    new_stock = origin_stock - int(count)
                    new_sales = sku.sales + int(count)

                    # update df_goods_sku set stock=new_stock, sales=new_sales
                    # where id=sku_id and stock=origin_stock
                    # 返回的是受影响的行数
                    res = GoodsSKU.objects.filter(id=sku_id, stock=origin_stock).update(stock=new_stock,sales=new_sales)
                    if res == 0:
                        if i == 2:
                            # 尝试3次没有成功
                            transaction.savepoint_rollback(save_id)
                            return JsonResponse({'res':7, 'errmsg': '下单失败2 '})
                        else:
                            continue
                    # todo:添加记录
                    OrderGoods.objects.create(order=order,
                                              sku=sku,
                                              count=count,
                                              price=price)

                    # todo: 计算订单商品的总金额和总数量
                    amount = sku.price*int(count)
                    total_price += amount
                    total_count += int(count)
                    # 跳出循环
                    break

            # todo: 更新订单信息表中的商品总数量和总价格
            order.total_count = total_count
            order.total_price = total_price
            order.save()
        except Exception as e:
            transaction.savepoint_rollback(save_id)
            return JsonResponse({'res':7, 'errmsg': '下单失败'})
        # 提交事务
        transaction.savepoint_commit(save_id)

        # todo: 清除用户购物车中对应的记录
        conn.hdel(cart_key, *sku_ids)

        return JsonResponse({'res':5, 'message': '创建成功'})