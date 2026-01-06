from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Sample data for ministries
ministries = [
    {"id": 1, "name": "Bộ Y tế", "url": "https://quantri-dvc.moh.gov.vn"},
    {"id": 2, "name": "Bộ Giáo dục và Đào tạo", "url": "https://quantridvc.moet.gov.vn/"},
    {"id": 3, "name": "Bộ Nội vụ", "url": "https://quantri-dvc.moha.gov.vn/"},
    {"id": 4, "name": "Bộ Khoa học Công nghệ", "url": "https://quantri.mst.gov.vn/vi/"},
    {"id": 5, "name": "Bộ Xây dựng", "url": "https://quantri.moc.gov.vn/"},
    {"id": 6, "name": "Bộ Nông nghiệp và môi trường", "url": "https://taikhoannguoidung-dvcnnmt.mae.gov.vn"},
    {"id": 7, "name": "Bộ Công Thương", "url": "https://quantri-tthc.moit.gov.vn"},
]

@app.route('/')
def index():
    return render_template('index.html', ministries=ministries)

@app.route('/search', methods=['POST'])
def search():
    keyword = request.form.get('keyword', '')
    search_type = request.form.get('type', 'all')

    # Filter ministries based on keyword
    results = []
    if keyword:
        results = [m for m in ministries if keyword.lower() in m['name'].lower()]
    else:
        results = ministries

    return jsonify({'results': results})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
