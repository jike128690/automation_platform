"""内置本地 Mock 站点（开发计划 T7.1）：静态 HTML 页面 + http.server 轻量服务，随客户端生命周期启停。

设计要点：
  - 登录页为 T7.1 核心验收（账号密码/按钮/校验，开放问题 01 默认方案）；
  - 同时提供 demo_cases 数据（M3 已提前就位）引用的全部页面与选择器，
    保证任何环境演示 100% 可用；
  - 服务轻量化（开发计划第 9 节）：ThreadingHTTPServer + daemon 线程，start/stop 随客户端启停。
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from app.config import MOCK_SITE_URL

LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Mock 登录</title></head><body>
<h2>Mock 站点 · 登录</h2>
<form id="login-form">
  <input id="username" placeholder="账号"><br>
  <input id="password" type="password" placeholder="密码"><br>
  <label><input id="remember" type="checkbox"> 记住登录状态</label><br>
  <button id="login-btn" type="button">登录</button>
</form>
<div id="login-error" style="display:none;color:#d32f2f">账号或密码错误</div>
<div id="user-info" style="display:none">欢迎，<span id="welcome"></span></div>
<button id="logout-btn" style="display:none">退出登录</button>
<p><a id="forgot-link" href="javascript:void(0)">忘记密码？</a></p>
<div id="reset-area" style="display:none">
  <input id="reset-email" placeholder="邮箱">
  <button id="reset-btn" type="button">发送重置邮件</button>
</div>
<div id="reset-ok" style="display:none">重置邮件已发送，请查收</div>
<script>
function showUser(u){
  document.getElementById('user-info').style.display='block';
  document.getElementById('welcome').textContent=u;
  document.getElementById('logout-btn').style.display='inline-block';
  document.getElementById('login-form').style.display='none';
}
if(localStorage.getItem('u'))showUser(localStorage.getItem('u'));
document.getElementById('login-btn').onclick=function(){
  var u=document.getElementById('username').value;
  var p=document.getElementById('password').value;
  if(u==='admin'&&p==='123456'){
    document.getElementById('login-error').style.display='none';
    localStorage.setItem('u',u);
    showUser(u);
  }else{
    document.getElementById('login-error').style.display='block';
  }
};
document.getElementById('logout-btn').onclick=function(){
  localStorage.removeItem('u');location.reload();
};
document.getElementById('forgot-link').onclick=function(){
  document.getElementById('reset-area').style.display='block';
};
document.getElementById('reset-btn').onclick=function(){
  document.getElementById('reset-ok').style.display='block';
};
</script>
</body></html>"""

REGISTER_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Mock 注册</title></head><body>
<h2>Mock 站点 · 注册</h2>
<input id="reg-username" placeholder="账号（至少 3 位）"><br>
<input id="reg-password" type="password" placeholder="密码（至少 6 位）"><br>
<button id="reg-btn" type="button">注册</button>
<div id="reg-error" style="display:none;color:#d32f2f">用户名至少 3 位，密码至少 6 位</div>
<div id="reg-ok" style="display:none">注册成功，请登录</div>
<script>
document.getElementById('reg-btn').onclick=function(){
  var u=document.getElementById('reg-username').value;
  var p=document.getElementById('reg-password').value;
  if(u.length>=3&&p.length>=6){
    document.getElementById('reg-error').style.display='none';
    document.getElementById('reg-ok').style.display='block';
  }else{
    document.getElementById('reg-error').style.display='block';
  }
};
</script>
</body></html>"""

INDEX_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Mock 首页</title></head><body>
<h2>Mock 站点 · 首页</h2>
<a id="nav-home" href="/index">首页</a> <a href="/cart">购物车</a> <a href="/orders">订单</a>
<div id="user-info" style="display:none">欢迎，<span id="welcome"></span></div><br>
<input id="search-input" placeholder="搜索商品"><button id="search-btn" type="button">搜索</button>
<button id="category-电子" type="button">电子</button>
<select id="sort-select"><option value="">排序</option><option id="sort-price" value="price">价格从低到高</option></select>
<div id="product-grid">
  <a id="product-1" href="/product/1">测试商品 1 - 智能手机（¥1999）</a><br>
  <span>测试商品 2 - 蓝牙耳机（¥299）</span><br>
  <span>测试商品 3 - 机械键盘（¥499）</span>
</div>
<div id="no-result" style="display:none">没有找到相关商品</div>
<button id="page-2" type="button">第 2 页</button>
<script>
if(localStorage.getItem('u')){
  document.getElementById('user-info').style.display='block';
  document.getElementById('welcome').textContent=localStorage.getItem('u');
}
document.getElementById('search-btn').onclick=function(){
  var q=document.getElementById('search-input').value;
  var grid=document.getElementById('product-grid');
  var no=document.getElementById('no-result');
  if(q==='zzz'||q===''){
    grid.style.display='none';no.style.display='block';
  }else{
    grid.style.display='block';no.style.display='none';
  }
};
</script>
</body></html>"""

PRODUCT_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Mock 商品</title></head><body>
<h2>Mock 站点 · 商品详情</h2>
<h1 id="product-title">测试商品 1 - 智能手机</h1>
<p>¥1999 · 支持货到付款</p>
<button id="add-cart-btn" type="button">加入购物车</button>
购物车：<span id="cart-count">0</span> 件
<script>
var n=0;
document.getElementById('add-cart-btn').onclick=function(){
  n+=1;document.getElementById('cart-count').textContent=n;
};
</script>
</body></html>"""

CART_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Mock 购物车</title></head><body>
<h2>Mock 站点 · 购物车</h2>
购物车：<span id="cart-count">1</span> 件<br>
<button id="checkout-btn" type="button">去结算</button>
<div id="checkout-area" style="display:none">
  <button id="submit-order-btn" type="button">提交订单</button>
  <button id="pay-btn" type="button">立即支付</button>
</div>
<div id="order-success" style="display:none">下单成功！</div>
<div id="pay-success" style="display:none">支付成功！</div>
<script>
document.getElementById('checkout-btn').onclick=function(){
  document.getElementById('checkout-area').style.display='block';
};
document.getElementById('submit-order-btn').onclick=function(){
  document.getElementById('order-success').style.display='block';
};
document.getElementById('pay-btn').onclick=function(){
  document.getElementById('pay-success').style.display='block';
};
</script>
</body></html>"""

ORDERS_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Mock 订单</title></head><body>
<h2>Mock 站点 · 我的订单</h2>
<button id="nav-orders" type="button">我的订单</button>
<div id="order-list">
  <div>订单 #1001 · ¥1999 · 2026-10-16</div>
  <button id="order-detail-btn" type="button">查看详情</button>
  <button id="cancel-order-btn" type="button">取消订单</button>
  <button id="edit-address-btn" type="button">修改收货地址</button>
  <button id="track-order-btn" type="button">物流跟踪</button>
  <button id="clear-orders-btn" type="button">清空历史订单</button>
</div>
<div id="order-info" style="display:none">订单详情：智能手机 ¥1999，顺丰快递</div>
<div id="order-cancelled" style="display:none">订单已取消</div>
<input id="address-input" placeholder="新收货地址" style="display:none">
<button id="save-address-btn" type="button">保存地址</button>
<div id="address-ok" style="display:none">收货地址已保存</div>
<div id="track-info" style="display:none">物流：已揽收，运输中</div>
<div id="orders-empty" style="display:none">暂无历史订单</div>
<script>
document.getElementById('order-detail-btn').onclick=function(){document.getElementById('order-info').style.display='block';};
document.getElementById('cancel-order-btn').onclick=function(){document.getElementById('order-cancelled').style.display='block';};
document.getElementById('edit-address-btn').onclick=function(){document.getElementById('address-input').style.display='inline-block';};
document.getElementById('save-address-btn').onclick=function(){document.getElementById('address-ok').style.display='block';};
document.getElementById('track-order-btn').onclick=function(){document.getElementById('track-info').style.display='block';};
document.getElementById('clear-orders-btn').onclick=function(){document.getElementById('order-list').style.display='none';document.getElementById('orders-empty').style.display='block';};
</script>
</body></html>"""

PAGES = {
    "/login": LOGIN_PAGE,
    "/register": REGISTER_PAGE,
    "/index": INDEX_PAGE,
    "/product/1": PRODUCT_PAGE,
    "/cart": CART_PAGE,
    "/orders": ORDERS_PAGE,
}


class _Handler(BaseHTTPRequestHandler):
    """静态页面服务：仅 GET，未知路径 404，访问日志静默。"""

    def do_GET(self):
        page = PAGES.get(urlparse(self.path).path)
        if page is None:
            self.send_error(404)
            return
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # 静默访问日志


class MockSite:
    """本地 Mock 站点：start() 在后台线程提供服务，stop() 停止（随客户端生命周期启停）。"""

    def __init__(self, url: str = MOCK_SITE_URL):
        parts = urlparse(url)
        self.host = parts.hostname or "127.0.0.1"
        self.port = parts.port or 8765
        self._server = None
        self._thread = None

    def start(self):
        if self._server is not None:
            return
        self._server = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None