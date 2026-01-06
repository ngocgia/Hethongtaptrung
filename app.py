from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
import requests
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'
app.permanent_session_lifetime = timedelta(hours=8)

# In-memory token storage
tokens_storage = {}  # {user_id: {ministry_id: {access_token, refresh_token, expires_at}}}

# Ministries configuration with SSO URLs
ministries = [
    {
        "id": 1,
        "name": "Bộ Y tế",
        "url": "https://quantri-dvc.moh.gov.vn",
        "sso_url": "https://sso-dvc.moh.gov.vn"
    },
    {
        "id": 2,
        "name": "Bộ Giáo dục và Đào tạo",
        "url": "https://quantridvc.moet.gov.vn/",
        "sso_url": "https://ssodvc.moet.gov.vn"
    },
    {
        "id": 3,
        "name": "Bộ Nội vụ",
        "url": "https://quantri-dvc.moha.gov.vn/",
        "sso_url": "https://sso-dvc.moha.gov.vn"
    },
    {
        "id": 4,
        "name": "Bộ Khoa học Công nghệ",
        "url": "https://quantri.mst.gov.vn/vi/",
        "sso_url": "https://ssodichvucong.mst.gov.vn"
    },
    {
        "id": 5,
        "name": "Bộ Xây dựng",
        "url": "https://quantri.moc.gov.vn/",
        "sso_url": "https://sso-motcua.moc.gov.vn"
    },
    {
        "id": 6,
        "name": "Bộ Nông nghiệp và môi trường",
        "url": "https://taikhoannguoidung-dvcnnmt.mae.gov.vn",
        "sso_url": "https://xacthuc-dvcnnmt.mae.gov.vn"
    },
    {
        "id": 7,
        "name": "Bộ Công Thương",
        "url": "https://quantri-tthc.moit.gov.vn",
        "sso_url": "https://sso-tthc.moit.gov.vn"
    },
]

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Login to ministry SSO
def login_ministry_sso(ministry, username, password):
    """Login to ministry SSO and get access token"""
    sso_url = ministry['sso_url']
    token_url = f"{sso_url}/auth/realms/digo/protocol/openid-connect/token"

    data = {
        'grant_type': 'password',
        'username': username,
        'password': password,
        'client_id': 'web-onegate'
    }

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
    }

    try:
        response = requests.post(token_url, data=data, headers=headers, timeout=10, allow_redirects=False)

        # Check content type before parsing JSON
        content_type = response.headers.get('content-type', '').lower()

        if response.status_code == 200 and 'application/json' in content_type:
            token_data = response.json()
            return {
                'access_token': token_data.get('access_token'),
                'refresh_token': token_data.get('refresh_token'),
                'expires_in': token_data.get('expires_in', 3600)
            }
        else:
            print(f"[{ministry['name']}] Status: {response.status_code}, Content-Type: {content_type}")
            if response.text:
                preview = response.text[:200]
                print(f"[{ministry['name']}] Response preview: {preview}")
    except requests.exceptions.RequestException as e:
        print(f"[{ministry['name']}] Request error: {e}")
    except Exception as e:
        print(f"[{ministry['name']}] Error: {e}")
    return None

def save_token(user_id, ministry_id, token_data):
    """Save token to in-memory storage"""
    if user_id not in tokens_storage:
        tokens_storage[user_id] = {}

    expires_at = datetime.now() + timedelta(seconds=token_data['expires_in'])

    tokens_storage[user_id][ministry_id] = {
        'access_token': token_data['access_token'],
        'refresh_token': token_data.get('refresh_token'),
        'expires_at': expires_at
    }

def get_user_tokens(user_id):
    """Get all tokens for a user from in-memory storage"""
    if user_id not in tokens_storage:
        return {}

    return tokens_storage[user_id]

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = {
        'username': session.get('username', ''),
        'full_name': session.get('full_name', session.get('username', ''))
    }
    return render_template('index.html', ministries=ministries, user=user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Thử login vào ít nhất 1 Bộ thành công
        login_success = False
        successful_ministry = None

        for ministry in ministries:
            token_data = login_ministry_sso(ministry, username, password)
            if token_data:
                login_success = True
                successful_ministry = ministry
                # Lưu token của Bộ này luôn
                save_token(username, ministry['id'], token_data)
                break

        if login_success:
            session['user_id'] = username
            session['username'] = username
            session['full_name'] = username
            session['ministry_username'] = username
            session['ministry_password'] = password
            session.permanent = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html',
                error=f'Không thể đăng nhập vào bất kỳ Bộ nào. Vui lòng kiểm tra lại username/password.')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/sync-tokens', methods=['POST'])
@login_required
def sync_tokens():
    """Sync all ministry tokens for current user"""
    user_id = session['user_id']
    ministry_username = session.get('ministry_username', '')
    ministry_password = session.get('ministry_password', '')

    if not ministry_username or not ministry_password:
        return jsonify({'error': 'Chưa có thông tin đăng nhập. Vui lòng đăng nhập lại.'})

    results = []

    for ministry in ministries:
        token_data = login_ministry_sso(ministry, ministry_username, ministry_password)
        if token_data:
            save_token(user_id, ministry['id'], token_data)
            results.append({
                'ministry_id': ministry['id'],
                'ministry_name': ministry['name'],
                'status': 'success'
            })
        else:
            results.append({
                'ministry_id': ministry['id'],
                'ministry_name': ministry['name'],
                'status': 'failed'
            })

    return jsonify({'results': results})

@app.route('/tokens')
@login_required
def list_tokens():
    """List all tokens for current user"""
    user_id = session['user_id']
    user_tokens = get_user_tokens(user_id)

    token_list = []
    for ministry in ministries:
        if ministry['id'] in user_tokens:
            token_info = user_tokens[ministry['id']]
            token_list.append({
                'ministry_id': ministry['id'],
                'ministry_name': ministry['name'],
                'has_token': True,
                'expires_at': token_info['expires_at'].isoformat()
            })
        else:
            token_list.append({
                'ministry_id': ministry['id'],
                'ministry_name': ministry['name'],
                'has_token': False
            })

    return jsonify({'tokens': token_list})

@app.route('/search', methods=['POST'])
@login_required
def search():
    keyword = request.form.get('keyword', '')
    search_type = request.form.get('type', 'all')

    results = []
    if keyword:
        results = [m for m in ministries if keyword.lower() in m['name'].lower()]
    else:
        results = ministries

    return jsonify({'results': results})

@app.route('/lookup-account', methods=['POST'])
@login_required
def lookup_account():
    """Tra cứu tài khoản trên tất cả các bộ"""
    keyword = request.form.get('keyword', '').strip()

    if not keyword:
        return jsonify({'error': 'Vui lòng nhập từ khóa tra cứu'})

    user_id = session['user_id']
    user_tokens = get_user_tokens(user_id)

    results = []

    # API URLs cho từng bộ
    api_urls = {
        1: 'https://api-dvc.moh.gov.vn/hu/user',  # Bộ Y tế
        2: 'https://apidvc.moet.gov.vn/hu/user',  # Bộ GD&ĐT
        3: 'https://api-dvc.moha.gov.vn/hu/user',  # Bộ Nội vụ
        4: 'https://apidichvucong.mst.gov.vn/hu/user',  # Bộ KH&CN
        5: 'https://api-motcua.moc.gov.vn/hu/user',  # Bộ Xây dựng
        6: 'https://apigateway-dvcnnmt.mae.gov.vn/hu/user',  # Bộ NN&MT
        7: 'https://api-tthc.moit.gov.vn/hu/user',  # Bộ Công Thương
    }

    for ministry in ministries:
        ministry_id = ministry['id']
        ministry_name = ministry['name']

        result = {
            'ministry_id': ministry_id,
            'ministry_name': ministry_name,
            'status': 'pending',
            'found': False,
            'accounts': [],
            'message': ''
        }

        # Kiểm tra token
        if ministry_id not in user_tokens:
            result['status'] = 'no_token'
            result['message'] = 'Chưa đồng bộ token'
            results.append(result)
            continue

        access_token = user_tokens[ministry_id]['access_token']

        # Kiểm tra token hết hạn
        if user_tokens[ministry_id]['expires_at'] < datetime.now():
            result['status'] = 'token_expired'
            result['message'] = 'Token đã hết hạn'
            results.append(result)
            continue

        # Gọi API tra cứu
        api_url = api_urls.get(ministry_id)

        if not api_url:
            result['status'] = 'error'
            result['message'] = 'Chưa cấu hình API'
            results.append(result)
            continue

        params = {
            'keyword': keyword,
            'ldap': 0,
            'page': 0,
            'size': 10,
            'sortField': 'fullname',
            'sortType': 'asc'
        }

        headers = {
            'accept': '*/*',
            'accept-language': 'vi,fr-FR;q=0.9,fr;q=0.8,en-US;q=0.7,en;q=0.6',
            'Authorization': f'Bearer {access_token}'
        }

        try:
            response = requests.get(api_url, params=params, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()

                # Kiểm tra cấu trúc response
                if data and 'content' in data:
                    accounts = data['content']
                    print(data)

                    if accounts and len(accounts) > 0:
                        result['status'] = 'success'
                        result['found'] = True
                        result['accounts'] = accounts
                        result['message'] = f'Tìm thấy {len(accounts)} tài khoản'
                    else:
                        result['status'] = 'success'
                        result['found'] = False
                        result['message'] = 'Không tìm thấy tài khoản'
                else:
                    result['status'] = 'success'
                    result['found'] = False
                    result['message'] = 'Không tìm thấy tài khoản'
            else:
                result['status'] = 'error'
                result['message'] = f'Lỗi API: HTTP {response.status_code}'

        except requests.exceptions.Timeout:
            result['status'] = 'error'
            result['message'] = 'Timeout'
        except requests.exceptions.RequestException as e:
            result['status'] = 'error'
            result['message'] = f'Lỗi kết nối: {str(e)[:50]}'
        except Exception as e:
            result['status'] = 'error'
            result['message'] = f'Lỗi: {str(e)[:50]}'

        results.append(result)

    return jsonify({'success': True, 'results': results, 'keyword': keyword})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
