import json
import queue
import os
from configparser import ConfigParser
from flask import Flask, request, jsonify
from flask_cors import CORS
import paginate
import ssl


def main():
    app.run(debug=False, host='0.0.0.0', port=5001, ssl_context=context)


context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
context.load_cert_chain('./nginx-ext/cert.pem', './nginx-ext/key.pem')

app = Flask(__name__)
CORS(app)

total = None
all_files = None


@app.route('/gallery/list', methods=['GET'])
def gallery_list():
    global total, all_files
    if total is None:
        total = str(len(os.listdir(images_dir)))
    if all_files is None:
        all_files = list([os.path.join('img', i) for i in os.listdir(images_dir)])

    page_number = request.args.get('pageNumber')
    page_size = request.args.get('pageSize')
    stride = int(request.args.get('stride'))

    files = all_files
    if stride is not None:
        files = files[::stride]
        total = str(len(files))

    if page_number is not None and page_size is not None:
        print("paginated, number: {}, size: {}".format(page_number, page_size))
        files = paginate.Page(files, page=int(page_number), items_per_page=int(page_size)).items

    return json.dumps({'items': files, 'total': total}), 200


if __name__ == '__main__':
    CONFIG = ConfigParser()
    CONFIG.read("gta-server.ini")
    images_dir = CONFIG["Images"]["Jpg"]
    main()
