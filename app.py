from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
import requests
from datetime import datetime, timedelta
import pandas as pd
import io
import os

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

def get_agency_tree(ministry, keyword, access_token):
    """Lấy thông tin agency từ API tree-view"""
    agency_api_urls = {
        1: 'https://api-dvc.moh.gov.vn/ba/agency/tree-view',  # Bộ Y tế
        2: 'https://apidvc.moet.gov.vn/ba/agency/tree-view',  # Bộ GD&ĐT
        3: 'https://api-dvc.moha.gov.vn/ba/agency/tree-view',  # Bộ Nội vụ
        4: 'https://apidichvucong.mst.gov.vn/ba/agency/tree-view',  # Bộ KH&CN
        5: 'https://api-motcua.moc.gov.vn/ba/agency/tree-view',  # Bộ Xây dựng
        6: 'https://apigateway-dvcnnmt.mae.gov.vn/ba/agency/tree-view',  # Bộ NN&MT
        7: 'https://api-tthc.moit.gov.vn/ba/agency/tree-view',  # Bộ Công Thương
    }

    api_url = agency_api_urls.get(ministry['id'])

    if not api_url:
        return None

    params = {
        'keyword': keyword,
        'agencyName': '',
        'code': '',
        'status': '',
        'levelId': '',
        'list-level-id': '',
        'phone': '',
        'parent-id': '',
        'tag-id': '',
        'sort': ''
    }

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }

    try:
        response = requests.get(api_url, params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()

            if data and 'content' in data and isinstance(data['content'], list) and len(data['content']) > 0:
                return data['content'][0]

        return None
    except Exception as e:
        print(f"DEBUG get_agency_tree error: {e}")
        return None


def update_user_experience(ministry, user_id, account_data, access_token):
    """Cập nhật quá trình công tác cho user"""
    experience_api_urls = {
        1: 'https://api-dvc.moh.gov.vn/hu/user',  # Bộ Y tế
        2: 'https://apidvc.moet.gov.vn/hu/user',  # Bộ GD&ĐT
        3: 'https://api-dvc.moha.gov.vn/hu/user',  # Bộ Nội vụ
        4: 'https://apidichvucong.mst.gov.vn/hu/user',  # Bộ KH&CN
        5: 'https://api-motcua.moc.gov.vn/hu/user',  # Bộ Xây dựng
        6: 'https://apigateway-dvcnnmt.mae.gov.vn/hu/user',  # Bộ NN&MT
        7: 'https://api-tthc.moit.gov.vn/hu/user',  # Bộ Công Thương
    }

    base_url = experience_api_urls.get(ministry['id'])

    if not base_url:
        return {'success': False, 'message': 'Chưa cấu hình API experience'}

    # Xử lý agency parent từ Excel - lấy trực tiếp từ agencyDepartment
    agency_parent = account_data.get('agencyParent', '')

    # Xử lý agency department từ Excel
    agency_dept_keyword = account_data.get('agencyDepartment', '')
    agency_dept_id = ""
    agency_dept_name = None
    agency_dept_parent_id = ""

    if agency_dept_keyword:
        # Gọi API tree-view để lấy thông tin agency department
        agency_dept_info = get_agency_tree(ministry, agency_dept_keyword, access_token)
        print(f"DEBUG update_user_experience: agency_dept_info = {agency_dept_info}")

        if agency_dept_info:
            # Xử lý tương tự như agency parent
            if 'content' in agency_dept_info:
                content = agency_dept_info['content']
                if isinstance(content, list) and len(content) > 0:
                    agency_dept_id = content[0].get('id', '')
                    agency_dept_name = content[0].get('name')
                    # Lấy parent_id từ content[0]
                    agency_dept_parent_id = content[0].get('id', '')
                elif isinstance(content, dict):
                    agency_dept_id = content.get('id', '')
                    agency_dept_name = content.get('name')
                    agency_dept_parent_id = content.get('id', '')
                else:
                    agency_dept_id = agency_dept_info.get('id', '')
                    agency_dept_name = agency_dept_info.get('name')
                    agency_dept_parent_id = agency_dept_info.get('id', '')
            else:
                agency_dept_id = agency_dept_info.get('id', '')
                agency_dept_name = agency_dept_info.get('name')
                agency_dept_parent_id = agency_dept_info.get('id', '')
    else:
        # Nếu không có agencyDepartment, sử dụng agencyParent làm agency chính
        agency_dept_parent_id = ""
        agency_dept_id = ""
        agency_dept_name = None

    # Xử lý position từ Excel
    position_keyword = account_data.get('position', '')
  
    match ministry['id']:
        case 1:  # Bộ Y tế
            match position_keyword:
                case "Cán bộ tiếp nhận":
                    position_id = "63da27faee48c32f84775aa7"
                    position_name = "Cán bộ một cửa"
                case "Chuyên viên":
                    position_id = "63d86b35ee48c32f84775a99"
                    position_name = "Chuyên viên"
                case "Lãnh đạo phòng":   
                    position_id = "63d86b2eee48c32f84775a98"
                    position_name = "Lãnh đạo"
                case "Lãnh đạo đơn vị":
                    position_id = "63d86b2eee48c32f84775a98"
                    position_name = "Lãnh đạo"
                case _:
                    position_id = "63d86b35ee48c32f84775a99"
                    position_name = "Chuyên viên"
        case 2:  # Bộ GD&ĐT
            match position_keyword:
                case "Cán bộ tiếp nhận":
                    position_id = "63da27faee48c32f84775aa7"
                    position_name = "Cán bộ một cửa"
                case "Chuyên viên":
                    position_id = "63d86b35ee48c32f84775a99"
                    position_name = "Chuyên viên"
                case "Lãnh đạo phòng":   
                    position_id = "676323499be21b2c69676323"
                    position_name = "Lãnh đạo phòng"
                case "Lãnh đạo đơn vị":
                    position_id = "67f7008a5caf25886f67f700"
                    position_name = "Lãnh đạo UBND"
                case _:
                    position_id = "63d86b35ee48c32f84775a99"
                    position_name = "Chuyên viên"
        case 3:  # Bộ Nội vụ
            match position_keyword:
                case "Cán bộ tiếp nhận":
                    position_id = "691403b85d64c445d3f144bb"
                    position_name = "Công chức tiếp nhận hồ sơ và TKQ"
                case "Lãnh đạo phòng":   
                    position_id = "67452ec3bcb70f68d3aa44d9"
                    position_name = "Lãnh đạo phòng"
                case "Lãnh đạo đơn vị":
                    position_id = "691403d7aaa2404972604d84"
                    position_name = "Lãnh đạo đơn vị"
                case "Chuyên viên":
                    position_id = "673d9ac1e83ede4465d14542"
                    position_name = "Chuyên viên"
                case _:
                    position_id = "673d9ac1e83ede4465d14542"
                    position_name = "Chuyên viên"
        case 4:  # Bộ KH&CN
            position_id = "63d86b35ee48c32f84775a99"
            position_name = "Chuyên viên"
        case 5:  # Bộ Xây dựng
            position_id = "63d86b35ee48c32f84775a99"
            position_name = "Chuyên viên"
        case 6:  # Bộ NN&MT
            position_id = "63d86b35ee48c32f84775a99"
            position_name = "Chuyên viên"
        case 7:  # Bộ Công Thương
            position_id = "63d86b35ee48c32f84775a99"
            position_name = "Chuyên viên"
        case _:
            position_id = "63d86b35ee48c32f84775a99"
            position_name = "Chuyên viên"
        # Nếu không có agency_dept_parent_id, sử dụng agency_dept_id
    if not agency_dept_parent_id and agency_dept_id:
        agency_dept_parent_id = agency_dept_id

    # Nếu vẫn không có, lấy từ keyword agencyParent
    if not agency_dept_parent_id and agency_parent:
        # Thử tìm agency parent từ API
        agency_info = get_agency_tree(ministry, agency_parent, access_token)
        if agency_info:
            if 'content' in agency_info:
                content = agency_info['content']
                if isinstance(content, list) and len(content) > 0:
                    agency_dept_parent_id = content[0].get('id', '')
                elif isinstance(content, dict):
                    agency_dept_parent_id = content.get('id', '')
            else:
                agency_dept_parent_id = agency_info.get('id', '')

    if not agency_dept_parent_id:
        return {'success': False, 'message': 'Không tìm thấy agency cha. Vui lòng kiểm tra mã đơn vị.'}

    print(f"DEBUG update_user_experience: agency_dept_parent_id = {agency_dept_parent_id}, agency_parent = {agency_parent}")

    # Chuẩn bị payload cho experience
    from datetime import datetime, timezone

    experience_payload = [
        {
            "agency": {
                "id": agency_dept_parent_id,
                "name": agency_parent
            },
            "agencyDepartment": {
                "id": agency_dept_id,
                "name": agency_dept_name
            },
            "position": {
                "id": position_id,  # Lấy từ API position
                "name": position_name
            },
            "startDate": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "endDate": None,
            "primary": True,
            "dynamicVariable": True
        }
    ]

    print(experience_payload)

    api_url = f"{base_url}/{user_id}/experience?checkAgencyEx=true"

    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'vi',
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Origin': ministry['url'],
        'Referer': ministry['url'] + '/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    try:
        response = requests.put(api_url, json=experience_payload, headers=headers, timeout=30)

        if response.status_code in [200, 201, 204]:
            return {'success': True, 'message': 'Cập nhật quá trình công tác thành công'}
        else:
            return {
                'success': False,
                'message': f'Lỗi cập nhật experience HTTP {response.status_code}',
                'details': response.text[:200] if response.text else ''
            }
    except requests.exceptions.Timeout:
        return {'success': False, 'message': 'Timeout khi cập nhật experience'}
    except requests.exceptions.RequestException as e:
        return {'success': False, 'message': f'Lỗi kết nối: {str(e)[:50]}'}
    except Exception as e:
        return {'success': False, 'message': f'Lỗi: {str(e)[:50]}'}

def create_account_on_ministry(ministry, account_data, access_token):
    """Tạo tài khoản trên một bộ"""
    api_urls = {
        1: 'https://api-dvc.moh.gov.vn/hu/user/--fully',  # Bộ Y tế
        2: 'https://apidvc.moet.gov.vn/hu/user/--fully',  # Bộ GD&ĐT
        3: 'https://api-dvc.moha.gov.vn/hu/user/--fully',  # Bộ Nội vụ
        4: 'https://apidichvucong.mst.gov.cn/hu/user/--fully',  # Bộ KH&CN
        5: 'https://api-motcua.moc.gov.vn/hu/user/--fully',  # Bộ Xây dựng
        6: 'https://apigateway-dvcnnmt.mae.gov.vn/hu/user/--fully',  # Bộ NN&MT
        7: 'https://api-tthc.moit.gov.vn/hu/user/--fully',  # Bộ Công Thương
    }

    api_url = api_urls.get(ministry['id'])

    if not api_url:
        return {'success': False, 'message': 'Chưa cấu hình API'}

    # Chuẩn bị dữ liệu theo format API
    payload = {
        "note": None,
        "fullname": account_data.get('fullname', ''),
        "birthday": None,
        "phoneNumber": [
            {
                "value": account_data.get('phoneNumber', '')
            }
        ] if account_data.get('phoneNumber') else [],
        "email": [
            {
                "value": account_data.get('email', '')
            }
        ] if account_data.get('email') else [],
        "gender": None,
        "identity": None,
        "ethnic": None,
        "religion": None,
        "address": None,
        "account": {
            "username": [
                {
                    "value": account_data.get('username', ''),
                    "type": 3  # Cán bộ
                }
            ],
            "password": account_data.get('password', ''),
            "verificationLevel": 1
        },
        "type": 3,  # Cán bộ
        "order": 1000,
        "taxCode": None
    }

    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'vi',
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Origin': ministry['url'],
        'Referer': ministry['url'] + '/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=30)

        if response.status_code in [200, 201]:
            # Lấy user_id từ response
            try:
                response_data = response.json()
                user_id = response_data.get('id') if isinstance(response_data, dict) else None

                # Nếu tạo thành công và có agencyParent thì cập nhật experience
                if user_id and account_data.get('agencyParent'):
                    experience_result = update_user_experience(ministry, user_id, account_data, access_token)

                    if experience_result['success']:
                        return {
                            'success': True,
                            'message': 'Tạo tài khoản và cập nhật quá trình công tác thành công',
                            'user_id': user_id
                        }
                    else:
                        return {
                            'success': True,
                            'message': 'Tạo tài khoản thành công nhưng lỗi cập nhật experience: ' + experience_result['message'],
                            'user_id': user_id,
                            'experience_error': experience_result['message']
                        }
                else:
                    return {
                        'success': True,
                        'message': 'Tạo tài khoản thành công',
                        'user_id': user_id
                    }
            except:
                return {'success': True, 'message': 'Tạo thành công'}
        else:
            return {
                'success': False,
                'message': f'Lỗi HTTP {response.status_code}',
                'details': response.text[:200] if response.text else ''
            }
    except requests.exceptions.Timeout:
        return {'success': False, 'message': 'Timeout'}
    except requests.exceptions.RequestException as e:
        return {'success': False, 'message': f'Lỗi kết nối: {str(e)[:50]}'}
    except Exception as e:
        return {'success': False, 'message': f'Lỗi: {str(e)[:50]}'}

@app.route('/import-accounts', methods=['POST'])
@login_required
def import_accounts():
    """Import tài khoản từ file Excel"""
    # Kiểm tra file
    if 'file' not in request.files:
        return jsonify({'error': 'Vui lòng chọn file Excel'})

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'Vui lòng chọn file Excel'})

    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'File phải có định dạng .xlsx hoặc .xls'})

    # Lấy danh sách bộ được chọn
    selected_ministries = request.form.get('ministries', '')

    if not selected_ministries:
        return jsonify({'error': 'Vui lòng chọn ít nhất một Bộ'})

    try:
        selected_ministry_ids = [int(x.strip()) for x in selected_ministries.split(',')]
    except:
        return jsonify({'error': 'Định dạng Bộ không hợp lệ'})

    # Đọc file Excel
    try:
        # Đọc Excel và chuyển tất cả các cột thành string để giữ nguyên định dạng
        df = pd.read_excel(file, engine='openpyxl', dtype=str)

        # Kiểm tra các cột bắt buộc
        required_columns = ['fullname', 'phoneNumber', 'email', 'username', 'password']
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            return jsonify({
                'error': f'Thiếu các cột bắt buộc: {", ".join(missing_columns)}'
            })

        # Lấy token của user
        user_id = session['user_id']
        user_tokens = get_user_tokens(user_id)

        results = []

        # Duyệt qua từng dòng trong Excel
        for index, row in df.iterrows():
            # Helper function để xử lý giá trị từ Excel
            def get_str_value(val):
                """Lấy giá trị string từ Excel, xử lý NaN và số"""
                if pd.isna(val):
                    return ''
                val_str = str(val).strip()
                # Nếu là số (ví dụ 6201004050.0), chuyển về string và bỏ .0
                if val_str.endswith('.0'):
                    val_str = val_str[:-2]
                return val_str

            account_data = {
                'fullname': get_str_value(row['fullname']),
                'phoneNumber': get_str_value(row['phoneNumber']),
                'email': get_str_value(row['email']),
                'username': get_str_value(row['username']),
                'password': get_str_value(row['password']),
                'agencyParent': get_str_value(row['agencyParent']) if 'agencyParent' in df.columns else '',
                'agencyDepartment': get_str_value(row['agencyDepartment']) if 'agencyDepartment' in df.columns else '',
                'position': get_str_value(row['position']) if 'position' in df.columns else ''
            }

            result = {
                'row': index + 2,  # +2 vì Excel bắt đầu từ hàng 1 và header là hàng 1
                'account': account_data,
                'ministries': []
            }

            # Tạo tài khoản trên từng bộ được chọn
            for ministry_id in selected_ministry_ids:
                ministry = next((m for m in ministries if m['id'] == ministry_id), None)

                if not ministry:
                    result['ministries'].append({
                        'ministry_id': ministry_id,
                        'ministry_name': 'Unknown',
                        'status': 'error',
                        'message': 'Không tìm thấy Bộ'
                    })
                    continue

                ministry_result = {
                    'ministry_id': ministry_id,
                    'ministry_name': ministry['name'],
                    'status': 'pending',
                    'message': ''
                }

                # Kiểm tra token
                if ministry_id not in user_tokens:
                    ministry_result['status'] = 'no_token'
                    ministry_result['message'] = 'Chưa đồng bộ token'
                    result['ministries'].append(ministry_result)
                    continue

                access_token = user_tokens[ministry_id]['access_token']

                # Kiểm tra token hết hạn
                if user_tokens[ministry_id]['expires_at'] < datetime.now():
                    ministry_result['status'] = 'token_expired'
                    ministry_result['message'] = 'Token đã hết hạn'
                    result['ministries'].append(ministry_result)
                    continue

                # Tạo tài khoản
                create_result = create_account_on_ministry(ministry, account_data, access_token)

                ministry_result['status'] = 'success' if create_result['success'] else 'error'
                ministry_result['message'] = create_result['message']
                if 'details' in create_result:
                    ministry_result['details'] = create_result['details']

                result['ministries'].append(ministry_result)

            results.append(result)

        # Thống kê kết quả
        total_accounts = len(results)
        total_operations = total_accounts * len(selected_ministry_ids)
        success_count = sum(
            1 for r in results
            for m in r['ministries']
            if m['status'] == 'success'
        )
        error_count = sum(
            1 for r in results
            for m in r['ministries']
            if m['status'] in ['error', 'no_token', 'token_expired']
        )

        return jsonify({
            'success': True,
            'results': results,
            'summary': {
                'total_accounts': total_accounts,
                'total_operations': total_operations,
                'success_count': success_count,
                'error_count': error_count
            }
        })

    except Exception as e:
        return jsonify({'error': f'Lỗi khi đọc file Excel: {str(e)}'})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
