from django.shortcuts import render
from django.views.generic import View
from django.http import JsonResponse

from django_redis import get_redis_connection

from goods.models import GoodsSKU
from utils.mixin import LoginRequiredMixin
# Create your views here.
# 添加商品到购物车：
# 1）请求方式：ajax, post
# 如果涉及到数据的修改（新增，更新，删除）,采用post
# 如果只是数据的获取，采用get
# 2)传递参数:商品id，商品数量


# cart/add
class CartAddView(View):
    '''购物车记录添加'''
    def post(self, request):
        '''购物车记录添加'''
        user = request.user
        if not user.is_authenticated():
            return JsonResponse({'res':0, 'errmsg': '用户未登录'})
        # 获取数据
        sku_id = request.POST.get('sku_id')
        count = request.POST.get('count')

        # 校验数据
        if not all([sku_id, count]):
            return JsonResponse({'res': 1, 'errmsg': '数据不完整'})
        try:
            count = int(count)
        except Exception as e:
            return JsonResponse({'res': 2, 'errmsg':'商品数目出错'})
        try:
            sku = GoodsSKU.objects.get(id=sku_id)
        except GoodsSKU.DoesNotExist:
            return JsonResponse({'res': 3, 'errmsg': '商品不存在'})

        # 业务处理，添加购物车记录
        conn = get_redis_connection('default')
        cart_key = 'cart_%d'%user.id
        # 先获取sku_id的直，hget cart_key
        # 如果不存在,hget返回None
        cart_count = conn.hget(cart_key, sku_id)
        if cart_count:
            count += int(cart_count)

        # 校验商品库存
        if count > sku.stock:
            return JsonResponse({'res': 4, 'errmsg': '商品库存不足'})
        # 设置hash中sku_id的直
        conn.hset(cart_key, sku_id, count)

        # 计算用户购物车商品的条目数
        total_count = conn.hlen(cart_key)

        # 返回应答
        return JsonResponse({'res': 5, 'total_count': total_count, 'message': '添加成功'})


# cart
class CartInfoView(LoginRequiredMixin, View):
    '''购物车页面'''
    def get(self, request):
        '''显示'''
        user = request.user
        conn = get_redis_connection('default')
        cart_key = 'cart_%d'%user.id
        # {'商品id': 商品数量}
        cart_dict = conn.hgetall(cart_key)

        skus = []
        # 保存用户购物车商品总数量和总价格
        total_count = 0
        total_price = 0
        for sku_id, count in cart_dict.items():
            # 获得商品信息
            sku = GoodsSKU.objects.get(id=sku_id)
            # 计算商品小记
            amount = sku.price * int(count)
            # 动态给sku对象添加一个属性amount，保存商品小记
            sku.amount = amount
            # 动态给sku对象添加一个属性count，保存购物车商品数量
            sku.count = count
            # 添加
            skus.append(sku)
            total_count += int(count)
            total_price += amount

        # 组织上下文
        context = {
            'total_count': total_count,
            'total_price': total_price,
            'skus': skus
        }

        return render(request, 'cart.html', context)


# 更新购物车记录
# 采用ajax post请求
# 传递参数，商品id(sku_id),商品数量(count)
# /cart/update
class CartUpdateView(View):
    '''更新购物车'''
    def post(self, request):
        '''购物车记录更新'''
        user = request.user
        if not user.is_authenticated():
            return JsonResponse({'res': 0, 'errmsg': '用户未登录'})
        # 获取数据
        sku_id = request.POST.get('sku_id')
        count = request.POST.get('count')
        # 校验数据
        if not all([sku_id, count]):
            return JsonResponse({'res': 1, 'errmsg': '数据不完整'})
        try:
            count = int(count)
        except Exception as e:
            return JsonResponse({'res': 2, 'errmsg':'商品数目出错'})
        try:
            sku = GoodsSKU.objects.get(id=sku_id)
        except GoodsSKU.DoesNotExist:
            return JsonResponse({'res': 3, 'errmsg': '商品不存在'})
        # 业务处理：更新购物车
        conn = get_redis_connection('default')
        cart_key = 'cart_%d'%user.id

        # 判断是否大于库存
        if count > sku.stock:
            return JsonResponse({'res': 4, 'errmsg': '库存不足'})

        # 更新
        conn.hset(cart_key, sku_id, count)
        # 返回应答

        # 计算用户购物车中上皮总件数
        total_count = 0
        vals = conn.hvals(cart_key)
        for val in vals:
            total_count += int(val)

        return JsonResponse({'res': 5, 'total_count': total_count, 'message': '更新成功'})



