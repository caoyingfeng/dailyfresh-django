from django.shortcuts import render, redirect
from django.core.urlresolvers import reverse
from django.views.generic import View

from django_redis import get_redis_connection

from goods.models import GoodsSKU
from user.models import Address
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
        context = {
            'addrs': addrs,
            'skus': skus,
            'total_count': total_count,
            'total_price': total_price,
            'transit_price': transit_price,
            'total_pay': total_pay
        }
        # 返回应答
        return render(request, 'place_order.html', context)