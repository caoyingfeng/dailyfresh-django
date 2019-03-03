#使用celery
from celery import Celery
from django.conf import settings
from django.core.mail import send_mail
from django.template import loader, RequestContext

from django_redis import get_redis_connection
import time
import os

#在任务端处理者一端加，用以初始化django环境
import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dailyfresh.settings")
django.setup()
# 导入的类应在初始化之后
from goods.models import GoodsType, IndexGoodsBanner,IndexPromotionBanner, IndexTypeGoodsBanner

#创建一个Celery对象
app = Celery('celery_tasks.tasks', broker='redis://192.168.1.139:6379/8')

#定义任务函数
@app.task
def send_register_active_email(to_email, username, token):
    '''发送激活邮件'''
    #组织邮件信息
    subject = '天天生鲜欢迎信息'
    message = ''
    sender = settings.EMAIL_FROM
    recevier = [to_email]
    html_message = '<h1>%s,欢迎您成为天天生鲜会员</h1>请点击下面的链接激活您的账户<br><a herf="http://127.0.0.1:8000/user/active/%s">http://127.0.0.1:8000/user/active/%s</a>' % (
    username, token, token)
    send_mail(subject, message, sender, recevier, html_message=html_message)
    #time.sleep(5)#测试延时


@app.task
def generate_static_index_html():
    '''显示首页'''
    # 获取商品的种类信息
    types = GoodsType.objects.all()
    # 获取首页轮播商品信息
    goods_banners = IndexGoodsBanner.objects.all().order_by('index')
    # 获取首页促销商品信息
    promotion_banners = IndexPromotionBanner.objects.all().order_by('index')
    # 获取首页分类商品展示信息
    # type_goods_banner = IndexTypeGoodsBanner.objects.all()
    for type in types:
        # 获取type种类首页分类商品图片展示信息
        image_banners = IndexTypeGoodsBanner.objects.filter(type=type, display_type=1)
        # 获取type种类首页分类商品文字展示信息
        title_banners = IndexTypeGoodsBanner.objects.filter(type=type, display_type=0)

        # 动态给type增加属性，分别保存首页分类商品的图片展示信息和文字展示信息
        type.image_banners = image_banners
        type.title_banners = title_banners


    # 组织上下文
    context = {'types': types,
               'goods_banners': goods_banners,
               'promotion_banners': promotion_banners}

    # 使用模板
    # 1.加载模板文件，返回模板对象
    temp = loader.get_template('static_index.html')
    # 2.定义模板上下文, 不依赖于request,可以省略
    #context = RequestContext(request, context)
    # 3. 模板渲染
    static_index_html = temp.render(context)

    # 生成首页对应静态文件
    save_path = os.path.join(settings.BASE_DIR, 'static/index.html')
    with open(save_path, 'w') as f:
        f.write(static_index_html)