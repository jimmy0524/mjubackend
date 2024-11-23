## 실행 방법
필요한 패키지를 설치합니다.
pip install -r requirements.txt
pip install flask-sqlalchemy pymysql cryptography

## 코드 설명
1. app.config와 SQLAlchemy를 통하여 데이터베이스를 설정합니다.
2. 데이터베이스 모델을 정의합니다. (User,Memo)
3. 홈 페이지(/)
쿠키에 userId가 존재하면 가져오고, 존재하지 않는다면 None을 name에 넣어서 index.html에 렌더링해줍니다.
4. OAuth (/auth)
네이버로부터 받은 authorization code를 사용하여 액세스 토큰을 받고, 사용자 정보를 가져옵니다.
얻어낸 user id와 name을 db에 저장하기 위해서, db에 쿼리를 날려 해당 사용자가 이미 존재하는지 확인하고, 존재하지 않는다면 db에 사용자 정보를 저장합니다.
5. 메모 목록 조회 (/memo GET)
DB에서 해당 userId의 메모들을 읽어오도록, 쿠키에서 가져온 userId로 User 객체를 찾고, 그 user 객체의 id와 memo의 user_id로 비교하여 모든 메모 목록을 가져와서 result에 넣고 memos라는 키 값으로 메모 목록을 보내줍니다.
5. 메모 작성 (/memo POST)
클라이언트로부터 받은 JSON에서 메모 내용을 추출하고, 마찬가지로 쿠키에서 가져온 userId로 User 객체를 찾고 그 객체의 id와 메모내용인 content로 새로운 Memo 객체를 생성하여 db에 저장합니다.