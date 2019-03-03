from django.shortcuts import render, redirect
from django.core.urlresolvers import reverse
from django.views.generic import View
from django.core.cache import cache
from django.core.paginator import Paginator

from goods.models import GoodsType, GoodsSKU, IndexGoodsBanner,IndexPromotionBanner, IndexTypeGoodsBanner
from django_redis import get_redis_connection
from order.models import OrderGoods
# Create your views here.


# http://127.0.0.1:8000
class IndexView(View):
    '''首页'''
    def get(self, request):
        '''显示首页'''
        context = cache.get('index_page_data')
        if context is None:
            print('设置缓存')
            # 缓存中没有数据
            # 获取商品的种类信息
            types = GoodsType.objects.all()
            # 获取首页轮播商品信息
            goods_banners = IndexGoodsBanner.objects.all().order_by('index')
            # 获取首页促销商品信息
            promotion_banners = IndexPromotionBanner.objects.all().order_by('index')
            # 获取首页分类商品展示信息
            #type_goods_banner = IndexTypeGoodsBanner.objects.all()
            for type in types:
                # 获取type种类首页分类商品图片展示信息
                image_banners = IndexTypeGoodsBanner.objects.filter(type=type, display_type=1)
                # 获取type种类首页分类商品文字展示信息
                title_banners = IndexTypeGoodsBanner.objects.filter(type=type, display_type=0)

                # 动态给type增加属性，分别保存首页分类商品的图片展示信息和文字展示信息
                type.image_banners = image_banners
                type.title_banners = title_banners

            context = {'types': types,
                       'goods_banners': goods_banners,
                       'promotion_banners': promotion_banners}
            # 设置缓存
            # key value timeout
            cache.set('index_page_data', context, 3600)
        # 获取用户购物车商品书目
        user = request.user
        cart_count = 0
        if user.is_authenticated():
            #用户登录
            conn = get_redis_connection('default')
            cart_key = 'cart_%d'%user.id
            cart_count = conn.hlen(cart_key)
        # 组织上下文
        context.update(cart_count=cart_count)

        return render(request, 'index.html', context)

# goods/id
class DetailView(View):
    '''详情页'''
    def get(self, request, goods_id):
        '''显示详情页'''
        try:
            sku = GoodsSKU.objects.get(id=goods_id)
        except GoodsSKU.DoesNotExist:
            # 商品不存在
            return redirect(reverse('goods:index'))

        # 获取商品的分类信息
        types = GoodsType.objects.all()

        # 获取商品的评论信息,排除评论为空的
        sku_orders = OrderGoods.objects.filter(sku=sku).exclude(comment='')

        # 获取新品信息,取两个
        new_skus = GoodsSKU.objects.filter(type=sku.type).order_by('-create_time')[:2]

        # 获取同一个SPU的其他规格商品
        same_spu_skus=GoodsSKU.objects.filter(goods=sku.goods).exclude(id=goods_id)

        # 获取用户购物车商品数目
        user = request.user
        cart_count = 0
        if user.is_authenticated():
            # 用户登录
            conn = get_redis_connection('default')
            cart_key = 'cart_%d' % user.id
            cart_count = conn.hlen(cart_key)

            # 添加用户的历史浏览记录
            conn = get_redis_connection('default')
            history_key = 'history_%d'%user.id
            # 移除列表中的goods_id
            conn.lrem(history_key, 0, goods_id)
            # 左侧插入goods_id
            conn.lpush(history_key, goods_id)
            # 只保存5条记录
            conn.ltrim(history_key, 0, 4)

        # 组织上下文
        context = {
            'sku': sku,
            'types': types,
            'sku_orders': sku_orders,
            'same_spu_skus': same_spu_skus,
            'new_skus': new_skus,
            'cart_count': cart_count,
        }
        return render(request, 'detail.html', context)


# list/种类id/页码?sort=排序方式
class ListView(View):
    '''列表页'''
    def get(self, request, type_id, page):
        '''显示列表页'''
        # 获取种类信息
        try:
            type = GoodsType.objects.get(id=type_id)
        except GoodsType.DoesNotExist:
            # 种类不存在
            return redirect(reverse('goods:index'))

        # 获取商品分类信息
        types = GoodsType.objects.all()

        # 获取排序方式 ，获取分类商品信息
        sort = request.GET.get('sort')
        # 商品id排序

        if sort == 'price':
            skus = GoodsSKU.objects.filter(type=type).order_by('price')
        elif sort == 'hot':
            skus = GoodsSKU.objects.filter(type=type).order_by('-sales')
        else:
            sort = 'default'
            skus = GoodsSKU.objects.filter(type=type).order_by('-id')

        # 对数据进行分页
        paginator = Paginator(skus, 1)

        # 获取第page页的内容
        try:
            page = int(page)
        except Exception as e:
            page = 1

        if page > paginator.num_pages:
            page = 1

        # 获取第page页的Page实例对象
        skus_page = paginator.page(page)

        # todo： 进行页码控制，页面上最多显示5个页码
        # 1.页面小于5个，显示全部
        # 2.页码是前3页，显示前5页
        # 3.页码是后3页，显示后5页
        # 4.其他情况，显示前2页，当前页，后2页
        num_pages = paginator.num_pages
        if num_pages < 5:
            pages = range(1, num_pages+1)
        elif page<=3:
            pages = range(1,6)
        elif num_pages - page <= 2:
            pages = range(num_pages-4, num_pages+1)
        else:
            pages = range(page-2, page+3)


        # 获取新品信息,取两个
        new_skus = GoodsSKU.objects.filter(type=type).order_by('-create_time')[:2]

        # 获取用户购物车商品数目
        user = request.user
        cart_count = 0
        if user.is_authenticated():
            # 用户登录
            conn = get_redis_connection('default')
            cart_key = 'cart_%d' % user.id
            cart_count = conn.hlen(cart_key)

        context = {
            'type': type,
            'types': types,
            'new_skus': new_skus,
            'skus_page': skus_page,
            'cart_count': cart_count,
            'pages': pages,
            'sort': sort
        }


        return render(request, 'list.html', context)