
from django.conf.urls import include, url
from cart.views import CartAddView, CartInfoView, CartUpdateView, CartDeleteView

urlpatterns = [
    url(r'^add$', CartAddView.as_view(), name='add'), # 购物车添加记录
    url(r'$', CartInfoView.as_view(), name='show'),
    url(r'^update$', CartUpdateView.as_view(), name='update'), # 购物车更新
    url(r'^deletd$', CartDeleteView.as_view(), name='delete'), # 购物车删除记录
]
