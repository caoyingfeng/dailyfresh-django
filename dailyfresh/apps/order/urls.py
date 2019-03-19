
from django.conf.urls import include, url
from order.views import OrderPlaceView, OrderCommitView,OrderPayView,CheckPayView

urlpatterns = [
    url(r'^place$', OrderPlaceView.as_view(), name='place'), # 提交订单页面显示
    url(r'^commit$', OrderCommitView.as_view(), name='commit'), # 订单创建
    url(r'^pay$', OrderPayView.as_view(), name='pay'), # 支付页面
    url(r'^check$', CheckPayView.as_view(), name='check'), # 检查订单支付状态
]

