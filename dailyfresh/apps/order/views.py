from django.shortcuts import render, redirect
from django.core.urlresolvers import reverse
from django.views.generic import View
from django.http import JsonResponse
from django.db import transaction
from django.conf import settings
from django_redis import get_redis_connection

from goods.models import GoodsSKU
from user.models import Address
from order.models import OrderInfo, OrderGoods

from datetime import datetime
import os

from utils.mixin import LoginRequiredMixin

from alipay import AliPay, ISVAliPay
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


# /order/pay
# ajax post
# 前端传递的参数： 订单id(order_id)
class OrderPayView(View):
    '''订单支付'''
    def post(self,request):
        '''订单支付'''
        # 用户登录校验
        user = request.user
        if not user.is_authenticated():
            return JsonResponse({'res':0, 'errmsg':'用户未登录'})
        # 接收参数
        order_id = request.POST.get('order_id')
        # 校验参数
        if not order_id:
            return JsonResponse({'res':1, 'errmsg':'无效的订单id'})

        try:
            order = OrderInfo.objects.get(order_id=order_id,
                                          user=user,
                                          pay_method=3,
                                          order_status=1)
        except Exception as e:
            return JsonResponse({'res':2, 'errmsg':'订单错误'})
        # 业务处理：使用python sdk调用支付宝支付接口
        app_private_key_string = os.path.join(settings.BASE_DIR, 'apps/order/app_private_key.pem')

        alipay_public_key_string = os.path.join(settings.BASE_DIR, 'apps/order/alipay_public_key.pem')
        # 初始化
        alipay = AliPay(
            appid='2016092600603394', #应用id
            app_notify_url=None,  # 默认回调url
            app_private_key_string=app_private_key_string,
            # 支付宝的公钥，验证支付宝回传消息使用，不是你自己的公钥,
            alipay_public_key_string=alipay_public_key_string,
            sign_type="RSA2",  # RSA 或者 RSA2
            debug = True  # 默认False
        )
        # 调用支付接口
        # 电脑网站支付，需要跳转到https://openapi.alipay.com/gateway.do? + order_string
        total_pay = order.total_price + order.transit_price # Decimal
        order_string = alipay.api_alipay_trade_page_pay(
            out_trade_no=order_id, # 订单id
            total_amount=str(total_pay), # 支付总金额
            subject='天天生鲜%d'%order_id,
            return_url=None,
            notify_url=None  # 可选, 不填则使用默认notify url
        )

        # 返回应答
        pay_url = 'https://openapi.alipaydev.com/gateway.do?' + order_string

        return JsonResponse({'res':3, 'pay_url': pay_url})


# /order/check
# ajax post
# 前端传递的参数： 订单id(order_id)
class CheckPayView(View):

    '''查询订单支付结果'''
    def post(self,request):
        '''查询支付结果'''

        # 用户登录校验
        user = request.user
        if not user.is_authenticated():
            return JsonResponse({'res': 0, 'errmsg': '用户未登录'})
        # 接收参数
        order_id = request.POST.get('order_id')
        # 校验参数
        if not order_id:
            return JsonResponse({'res': 1, 'errmsg': '无效的订单id'})

        try:
            order = OrderInfo.objects.get(order_id=order_id,
                                          user=user,
                                          pay_method=3,
                                          order_status=1)
        except Exception as e:
            return JsonResponse({'res': 2, 'errmsg': '订单错误'})
        # 业务处理：使用python sdk调用支付宝支付接口
        app_private_key_string = os.path.join(settings.BASE_DIR, 'apps/order/app_private_key.pem')

        alipay_public_key_string = os.path.join(settings.BASE_DIR, 'apps/order/alipay_public_key.pem')
        # 初始化
        alipay = AliPay(
            appid='2016092600603394',  # 应用id
            app_notify_url=None,  # 默认回调url
            app_private_key_string=app_private_key_string,
            # 支付宝的公钥，验证支付宝回传消息使用，不是你自己的公钥,
            alipay_public_key_string=alipay_public_key_string,
            sign_type="RSA2",  # RSA 或者 RSA2
            debug=True  # 默认False
        )
        while True:
            # 调用支付宝交易查询接口
            response = alipay.api_alipay_trade_query(order_id)
            '''
            response = {          
                "trade_no": "2017032121001004070200176844", # 支付宝交易号
                "code": "10000", # 接口调用是否成功
                "invoice_amount": "20.00",
                "open_id": "20880072506750308812798160715407",
                "fund_bill_list": [
                  {
                    "amount": "20.00",
                    "fund_channel": "ALIPAYACCOUNT"
                  }
                ],
                "buyer_logon_id": "csq***@sandbox.com",
                "send_pay_date": "2017-03-21 13:29:17",
                "receipt_amount": "20.00",
                "out_trade_no": "out_trade_no15",
                "buyer_pay_amount": "20.00",
                "buyer_user_id": "2088102169481075",
                "msg": "Success",
                "point_amount": "0.00",
                "trade_status": "TRADE_SUCCESS", # 支付结果
                "total_amount": "20.00"
              },
            '''
            code = response.get('code')

            if code=='1000' and response.get('trade_status')=='TRADE_SUCCESS':
                # 支付成功
                # 获取支付宝交易号
                trade_no = response.get('trade_no')
                # 更新订单状态
                order.trade_no = trade_no
                order.order_status = 4 # 待评价
                order.save()
                # 返回结果
                return JsonResponse({'res': 3, 'message':'支付成功'})
            elif code=='40004' or (code=='1000' and response.get('trade_status')=='WAIT_BUYER_PAY'):
                # 业务处理失败，需要等待或等待买家付款
                import time
                time.time(5)
                continue
            else:
                # 支付出错
                return JsonResponse({'res':4, 'errmsg': '支付失败'})



class CommentView(LoginRequiredMixin, View):
    '''订单评论'''
    def get(self, request, order_id):
        '''提供评论页面'''
        user = request.user

        # 校验数据
        if not order_id:
            return redirect(reverse('user:order'))
        try:
            order = OrderInfo.objects.get(id=order_id, user=user)
        except OrderGoods.DoesNotExist:
            return redirect(reverse('user:order'))

        # 根据订单状态获取状态标题
        order.status_name = OrderInfo.ORDER_STATUS[order.order_status]
        # 获取订单商品信息
        order_skus = OrderGoods.objects.filter(order_id=order_id)
        for order_sku in order_skus:
            # 计算商品的小计
            amount = order_sku.count*order_sku.price
            # 动态给order_sku保存amount属性，保存商品属性
            order_sku.amount = amount
        # 动态给order增加属性order_skus,保存订单商品信息
        order.order_skus = order_skus
        # 使用模板
        return render(request, 'order_comment.html', {'order':order})

    def post(self, request, order_id):
        '''处理评论页面'''
        user= request.user
        # 校验数据
        if not order_id:
            return redirect(reverse('user:order'))
        try:
            order = OrderInfo.objects.get(id=order_id, user=user)
        except OrderGoods.DoesNotExist:
            return redirect(reverse('user:order'))

        # 获取评论条数
        total_count = request.POST.get('total_count')
        total_count = int(total_count)
        # 循环获取订单中商品的评论内容
        for i in range(1, total_count+1):
            # 获取评论的商品id
            sku_id = request.POST.get('sku_%d'%i)
            # 获取评论的商品内容
            content = request.POST.get('content_%d'%i, '')
            try:
                order_goods = OrderGoods.objects.get(order=order, sku_id=sku_id)
            except OrderGoods.DoesNotExist:
                continue

            order_goods.comment = content
            order_goods.save()

        order.order_status = 5 # 已完成
        order.save()

        return redirect(reverse("user:order", kwargs={"page": 1}))