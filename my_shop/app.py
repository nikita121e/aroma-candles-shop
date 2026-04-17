import stripe
import os
import uuid
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = '123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///aroma_dublin_v3.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

stripe.api_key = "123"

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    address = db.Column(db.String(200))
    city = db.Column(db.String(50))
    postcode = db.Column(db.String(20))
    phone = db.Column(db.String(20))
    is_admin = db.Column(db.Boolean, default=False)
    is_active_account = db.Column(db.Boolean, default=True)
    date_joined = db.Column(db.DateTime, default=datetime.utcnow)
    
    cart_items = db.relationship('CartItem', backref='user', lazy=True, cascade="all, delete-orphan")
    wishlist = db.relationship('Wishlist', backref='user', lazy=True, cascade="all, delete-orphan")
    reviews = db.relationship('Review', backref='user', lazy=True)
    orders = db.relationship('Order', backref='user', lazy=True)

class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), default='Classic')
    description = db.Column(db.Text, nullable=True)
    image_file = db.Column(db.String(100), nullable=False, default='default.jpg')
    stock = db.Column(db.Integer, default=50)
    is_featured = db.Column(db.Boolean, default=False)
    discount_price = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    reviews = db.relationship('Review', backref='product', lazy=True, cascade="all, delete-orphan")

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship('Product')

class Wishlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    product = db.relationship('Product')

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=False)
    is_approved = db.Column(db.Boolean, default=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

class Coupon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    discount_percent = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    expiry_date = db.Column(db.DateTime)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True)
    order_date = db.Column(db.DateTime, default=datetime.utcnow)
    total_paid = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='Processing')
    payment_id = db.Column(db.String(100))
    shipping_address = db.Column(db.String(255))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    items = db.relationship('OrderItem', backref='order', lazy=True)

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_name = db.Column(db.String(100), nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.template_filter('format_euro')
def format_euro(value):
    return f"€{value:,.2f}"

@app.context_processor
def global_vars():
    def get_cart_stats():
        if current_user.is_authenticated:
            count = sum(item.quantity for item in current_user.cart_items)
            total = sum(item.product.price * item.quantity for item in current_user.cart_items)
            return {'count': count, 'total': total}
        return {'count': 0, 'total': 0}
    return dict(cart_stats=get_cart_stats())

@app.route('/')
def index():
    cat = request.args.get('category')
    sort = request.args.get('sort')
    if cat:
        products = Product.query.filter_by(category=cat)
    else:
        products = Product.query
    if sort == 'price_asc':
        products = products.order_by(Product.price.asc())
    elif sort == 'price_desc':
        products = products.order_by(Product.price.desc())
    else:
        products = products.order_by(Product.created_at.desc())
    return render_template('index.html', products=products.all())

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    p = Product.query.get_or_404(product_id)
    related = Product.query.filter(Product.category == p.category, Product.id != p.id).limit(4).all()
    return render_template('product_detail.html', product=p, related=related)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')
        email = f"{u.lower()}@aroma.ie"
        if User.query.filter_by(username=u).first():
            flash('Error: This username is already taken.', 'danger')
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(p, method='pbkdf2:sha256')
        user = User(username=u, email=email, password=hashed_pw)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please sign in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user, remember=True)
            return redirect(url_for('index'))
        flash('Invalid credentials. Please try again.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('index'))

@app.route('/cart')
@login_required
def cart():
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    subtotal = sum(i.product.price * i.quantity for i in items)
    discount = session.get('discount', 0)
    total = subtotal * (1 - discount/100)
    return render_template('cart.html', items=items, subtotal=subtotal, total=total)

@app.route('/cart/add/<int:product_id>')
@login_required
def add_to_cart(product_id):
    p = Product.query.get_or_404(product_id)
    if p.stock <= 0:
        flash('Out of stock!', 'warning')
        return redirect(url_for('index'))
    item = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if item:
        item.quantity += 1
    else:
        db.session.add(CartItem(user_id=current_user.id, product_id=product_id))
    db.session.commit()
    flash(f'{p.name} added to cart.', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/cart/update', methods=['POST'])
@login_required
def update_cart():
    for key, value in request.form.items():
        if key.startswith('quantity_'):
            item_id = key.split('_')[1]
            item = CartItem.query.get(item_id)
            if item and item.user_id == current_user.id:
                new_qty = int(value)
                if new_qty > 0:
                    item.quantity = new_qty
                else:
                    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('cart'))

@app.route('/cart/remove/<int:item_id>')
@login_required
def remove_from_cart(item_id):
    item = CartItem.query.get_or_404(item_id)
    if item.user_id == current_user.id:
        db.session.delete(item)
        db.session.commit()
    return redirect(url_for('cart'))

@app.route('/apply_coupon', methods=['POST'])
@login_required
def apply_coupon():
    code = request.form.get('coupon_code')
    coupon = Coupon.query.filter_by(code=code, is_active=True).first()
    if coupon:
        session['discount'] = coupon.discount_percent
        flash(f'Coupon applied! {coupon.discount_percent}% off.', 'success')
    else:
        flash('Invalid or expired coupon.', 'danger')
    return redirect(url_for('cart'))

@app.route('/wishlist')
@login_required
def wishlist():
    items = Wishlist.query.filter_by(user_id=current_user.id).all()
    return render_template('wishlist.html', items=items)

@app.route('/wishlist/toggle/<int:product_id>')
@login_required
def toggle_wishlist(product_id):
    exist = Wishlist.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if exist:
        db.session.delete(exist)
        flash('Removed from wishlist.', 'info')
    else:
        db.session.add(Wishlist(user_id=current_user.id, product_id=product_id))
        flash('Added to wishlist.', 'success')
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.first_name = request.form.get('first_name')
        current_user.last_name = request.form.get('last_name')
        current_user.address = request.form.get('address')
        current_user.phone = request.form.get('phone')
        db.session.commit()
        flash('Profile updated.', 'success')
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.order_date.desc()).all()
    return render_template('profile.html', user=current_user, orders=orders)

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    if not items:
        return redirect(url_for('index'))
    discount = session.get('discount', 0)
    line_items = []
    for i in items:
        line_items.append({
            'price_data': {
                'currency': 'eur',
                'product_data': {'name': i.product.name},
                'unit_amount': int(i.product.price * (1 - discount/100) * 100),
            },
            'quantity': i.quantity,
        })
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('cart', _external=True),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return str(e)

@app.route('/payment/success')
@login_required
def payment_success():
    stripe_session_id = request.args.get('session_id')
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    if not items:
        return redirect(url_for('index'))
    subtotal = sum(i.product.price * i.quantity for i in items)
    discount = session.get('discount', 0)
    final_total = subtotal * (1 - discount/100)
    order = Order(
        order_number=str(uuid.uuid4())[:8].upper(),
        total_paid=final_total,
        user_id=current_user.id,
        payment_id=stripe_session_id,
        shipping_address=current_user.address or "Digital Delivery/Pickup"
    )
    db.session.add(order)
    db.session.flush()
    for i in items:
        oi = OrderItem(order_id=order.id, product_name=i.product.name, unit_price=i.product.price, quantity=i.quantity)
        db.session.add(oi)
        i.product.stock -= i.quantity
        db.session.delete(i)
    db.session.commit()
    session.pop('discount', None)
    return render_template('success.html', order=order)

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        abort(403)
    p_count = Product.query.count()
    o_count = Order.query.count()
    u_count = User.query.count()
    recent_orders = Order.query.order_by(Order.order_date.desc()).limit(10).all()
    return render_template('admin.html', p_count=p_count, o_count=o_count, u_count=u_count, orders=recent_orders)

@app.route('/admin/products', methods=['GET', 'POST'])
@login_required
def admin_products():
    if not current_user.is_admin: abort(403)
    if request.method == 'POST':
        name = request.form.get('name')
        price = float(request.form.get('price'))
        cat = request.form.get('category')
        desc = request.form.get('description')
        new_p = Product(name=name, price=price, category=cat, description=desc)
        db.session.add(new_p)
        db.session.commit()
        flash('Product added!', 'success')
    products = Product.query.all()
    return render_template('admin_products.html', products=products)

@app.route('/api/search')
def api_search():
    query = request.args.get('q', '')
    results = Product.query.filter(Product.name.like(f'%{query}%')).all()
    return jsonify([{'id': p.id, 'name': p.name, 'price': p.price} for p in results])

@app.errorhandler(404)
def error_404(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def error_500(error):
    db.session.rollback()
    return render_template('500.html'), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not Product.query.first():
            db.session.add_all([
                Product(name="Dublin Sunset", price=19.99, category="Signature", is_featured=True, description="Warm vanilla"),
                Product(name="Atlantic Breeze", price=22.50, category="Nature", description="Sea salt & Sage"),
                Product(name="Wild Connemara", price=18.00, category="Nature", description="Moss & Heather"),
                Product(name="Galway Mist", price=20.00, category="Classic", description="Rain & Flowers"),
                Product(name="Celtic Rose", price=17.50, category="Floral", description="Garden Rose"),
                Product(name="Irish Hearth", price=25.00, category="Signature", description="Wood smoke"),
                Product(name="Belfast Linen", price=19.00, category="Classic", description="Fresh linen"),
                Product(name="Wicklow Orchard", price=21.00, category="Floral", description="Apple blossom")
            ])
        if not Coupon.query.filter_by(code='AROMA20').first():
            db.session.add(Coupon(code='AROMA20', discount_percent=20))
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', email='admin@aroma.ie', is_admin=True,
                         password=generate_password_hash('dublin2026', method='pbkdf2:sha256'))
            db.session.add(admin)
        db.session.commit()
    app.run(debug=True, port=5000)