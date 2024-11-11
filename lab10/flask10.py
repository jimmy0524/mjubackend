from flask import Flask, request, jsonify

app = Flask(__name__)

def calculate(arg1, op, arg2):
    if op == '+':
        return arg1 + arg2
    elif op == '-':
        return arg1 - arg2
    elif op == '*':
        return arg1 * arg2
    else:
        return None

@app.route('/<int:arg1>/<op>/<int:arg2>', methods=['GET'])
def calculate_get(arg1, op, arg2):
    result = calculate(arg1, op, arg2)
    if result is not None:
        return jsonify({'result': result}), 200
    else:
        return jsonify({'error': '지원하지 않는 연산자입니다.'}), 400

@app.route('/', methods=['POST'])
def calculate_post():
    data = request.get_json()
    if 'arg1' in data and 'op' in data and 'arg2' in data:
        arg1 = data['arg1']
        op = data['op']
        arg2 = data['arg2']
        result = calculate(arg1, op, arg2)
        if result is not None:
            return jsonify({'result': result}), 200
        else:
            return jsonify({'error': '지원하지 않는 연산자입니다.'}), 400
    else:
        return jsonify({'error': '필요한 데이터가 누락되었습니다.'}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=20125)
