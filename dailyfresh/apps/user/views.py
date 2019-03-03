from django.shortcuts import render, redirect
from django.core.urlresolvers import reverse
#from django.urls import reverse#django version 2.1.7
from django.views.generic import View
from django.conf import settings
from django.http import HttpResponse
from django.core.mail import send_mail
from django.contrib.auth import authenticate, login, logout

import re
from user.models import User, Address
from goods.models import GoodsSKU
from celery_tasks.tasks import send_register_active_email
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from itsdangerous import SignatureExpired
from utils.mixin import LoginRequiredMixin
from django_redis import get_redis_connection
# Create your views here.


def register(request):
    """注册"""
    #显示注册页面
    if request.method == 'GET':
        return render(request, 'register.html')
    else:
        #注册处理函数
        # 接受数据
        username = request.POST.get('user_name')
        pwd = request.POST.get('pwd')
        email = request.POST.get('email')
        allow = request.POST.get('allow')
        # 进行校验
        if not all([username, pwd, email]):
            return render(request, 'register.html', {'errmsg': '数据不完整'})
        # 校验邮箱
        if not re.match(r'^[a-z0-9][\w.\-]*@[a-z0-9\-]+(\.[a-z]{2,5}){1,2}$', email):
            return render(request, 'register.html', {'errmsg': '邮箱格式本正确'})

        # 用户名是否存在
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            user = None

        if user:
            return render(request, 'register.html', {'errmsg': '用户名已存在'})

        # 业务处理：用户注册
        if allow != 'on':
            return render(request, 'register.html', {'errmsg': '请同意协议'})
        user = User.objects.create_user(username, email, pwd)
        user.is_active = 0
        user.save()
        # 返回应答
        return redirect(reverse('goods:index'))


def register_handle(request):
    '''注册处理函数'''
    # 接受数据
    username = request.POST.get('user_name')
    pwd = request.POST.get('pwd')
    email = request.POST.get('email')
    allow = request.POST.get('allow')
    # 进行校验
    if not all([username, pwd, email]):
        return render(request, 'register.html', {'errmsg': '数据不完整'})
    # 校验邮箱
    if not re.match(r'^[a-z0-9][\w.\-]*@[a-z0-9\-]+(\.[a-z]{2,5}){1,2}$', email):
        return render(request, 'register.html', {'errmsg': '邮箱格式本正确'})

    # 用户名是否存在
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        user = None

    if user:
        return render(request, 'register.html', {'errmsg': '用户名已存在'})

    # 业务处理：用户注册
    if allow != 'on':
        return render(request, 'register.html', {'errmsg': '请同意协议'})
    user = User.objects.create_user(username, email, pwd)
    user.is_active = 0
    user.save()
    # 返回应答
    return redirect(reverse('goods:index'))


#/user/register
class RegisterView(View):
    '''注册'''
    def get(self, request):
        '''注册页面'''
        return render(request, 'register.html')

    def post(self,request):
        '''进行注册处理'''
        '''注册处理函数'''
        # 接受数据
        username = request.POST.get('user_name')
        pwd = request.POST.get('pwd')
        email = request.POST.get('email')
        allow = request.POST.get('allow')
        # 进行校验
        if not all([username, pwd, email]):
            return render(request, 'register.html', {'errmsg': '数据不完整'})
        # 校验邮箱
        if not re.match(r'^[a-z0-9][\w.\-]*@[a-z0-9\-]+(\.[a-z]{2,5}){1,2}$', email):
            return render(request, 'register.html', {'errmsg': '邮箱格式本正确'})

        # 用户名是否存在
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            user = None

        if user:
            return render(request, 'register.html', {'errmsg': '用户名已存在'})

        # 业务处理：用户注册
        if allow != 'on':
            return render(request, 'register.html', {'errmsg': '请同意协议'})
        user = User.objects.create_user(username, email, pwd)
        user.is_active = 0
        user.save()

        #发送激活邮件，包含激活链接http://127.0.0.1:8000/user/active/3
        #激活链接中需要包含用户信息，并把身份信息加密

        #加密用户身份信息，生成激活token
        serializer = Serializer(settings.SECRET_KEY, 3600)
        info = {'confirm': user.id}
        token = serializer.dumps(info)
        token = token.decode('utf8')

        #发送邮件
        send_register_active_email.delay(email, username, token)
        # 返回应答
        return redirect(reverse('goods:index'))



class ActiveView(View):
    '''用户激活'''
    def get(self, request, token):
        serializer = Serializer(settings.SECRET_KEY, 3600)
        try:
            info = serializer.loads(token)
            #获取用户id
            user_id = info['confirm']
            user = User.objects.get(id=user_id)
            user.is_active = 1
            user.save()
            #跳转到登陆页面
            return redirect(reverse('user:login'))
        except SignatureExpired as e:
            #链接已过期
            return HttpResponse('激活链接已过期')


#/user/login
class LoginView(View):
    '''用户登录'''
    def get(self,request):
        '''显示登录页面'''
        # 判断是否记住了用户名
        if 'username' in request.COOKIES:
            username = request.COOKIES.get('username')
            checked = 'checked'
        else:
            username = ''
            checked = ''
        return render(request, 'login.html', {'username': username, 'checked': checked})

    def post(self, request):
        '''用户登录处理'''
        username = request.POST.get('username')
        password = request.POST.get('pwd')

        # 校验数据
        if not all([username, password]):
            return render(request, 'login.html', {'errmsg': '数据不完整'})

        # 业务处理，登录验证
        user = authenticate(username=username, password=password)
        if user is not None:
            if user.is_active:
                # 用户激活，记录登录状态
                login(request, user)

                # 获取登录后所要跳转的地址
                # 默认跳转到首页
                next_url = request.GET.get('next', reverse('goods:index'))
                response = redirect(next_url)

                #判断是否需要记住用户名
                remember = request.POST.get('remember')

                if remember == 'on':
                    response.set_cookie('username', username, max_age=7*24*3600)
                else:
                    response.delete_cookie('username')

                return response

            else:
                return render(request, 'login.html', {'errmsg': '用户未激活'})
        else:
            return render(request, 'login.html', {'errmsg': '用户名或密码错误'})


# /user/logout
class LogoutView(View):
    '''退出登录'''
    def get(self, request):
        '''退出登录'''
        logout(request)
        return redirect(reverse('goods:index'))


# /user
class UserInfoView(LoginRequiredMixin, View):
    '''用户中心-信息页'''
    def get(self, request):
        '''显示'''
        # page='user'
        # request.user
        # 如果用户为登录->user是 AnonymousUser的一个实例
        # 如果登录，user 是User类的一个实例
        # .is_authenticated()
        # 除了给模板文件传递的模板变量之外, django框架会把request.user也传递给模板文件

        # 获取用户个人信息
        user = request.user
        address = Address.objects.get_default_address(user)
        # 获取用户浏览信息
        # from redis import StrictRedis
        # sr = StrictRedis(host='192.168.1.139', port='6379', db=9)
        con = get_redis_connection('default')

        history_key = 'history_%d'%user.id

        # 获取用户最新浏览的商品id
        sku_ids = con.lrange(history_key, 0, 4)

        goods_li = []
        for id in sku_ids:
            goods = GoodsSKU.objects.get(id=id)
            goods_li.append(goods)

        context = {'page': 'user',
                   'address': address,
                   'goods_li':goods_li}
        # 除了给模板文件传递的模板变量之外，django框架会把request.user也传给模板文件
        return render(request, 'user_center_info.html', context)


# /user/order
class UserOrderView(LoginRequiredMixin, View):
    '''用户中心-订单'''
    def get(self, request):
        '''显示'''
        #page='order'
        # 获取用户订单信息
        return render(request, 'user_center_order.html', {'page': 'order'})


# /user/address
class AddressView(LoginRequiredMixin, View):
    '''用户中心-地址'''
    def get(self, request):
        '''显示'''
        #page='address'
        # 获取用户默认收获地址
        user = request.user
        # try:
        #     address = Address.objects.get(user=user, is_default=True)
        # except Address.DoesNotExist:
        #     # 不存在默认收货地址
        #     address = None
        address = Address.objects.get_default_address(user)
        return render(request, 'user_center_site.html', {'page': 'address', 'address':address})

    def post(self, request):
        '''添加地址'''
        # 接受数据
        receiver = request.POST.get('receiver')
        addr = request.POST.get('addr')
        zip_code = request.POST.get('zip_code')
        phone = request.POST.get('phone')
        # 校验数据
        if not all([receiver, addr, phone]):
            return render(request, 'user_center_site.html', {'errmsg': '数据不完整'})
        # 校验手机号
        if not re.match(r'^1[3|4|5|7|8][0-9]{9}$', phone):
            return render(request, 'user_center_site.html', {'errmsg': '手机号不正确'})
        # 业务处理：添加地址
        # 如果用户已经存在默认收货地址，添加的地址不作为默认收货地址，否则作为默认收货地址
        # 获取登录用户对对应User对象
        user = request.user

        address = Address.objects.get_default_address(user)

        if address:
            is_default = False
        else:
            is_default = True

        # 添加地址
        Address.objects.create(user=user,
                               receiver=receiver,
                               addr=addr,
                               zip_code=zip_code,
                               phone=phone,
                               is_default=is_default)

        # 返回应答,刷新地址页
        return redirect(reverse('user:address')) # get请求方式
