import threading
import socket
import select
import queue
import json
import argparse
from enum import Enum
import message_pb2 as pb 


class MessageType(Enum):
    CS_NAME = 'CSName'
    CS_ROOMS = 'CSRooms'
    CS_CREATE_ROOM = 'CSCreateRoom'
    CS_JOIN_ROOM = 'CSJoinRoom'
    CS_LEAVE_ROOM = 'CSLeaveRoom'
    CS_CHAT = 'CSChat'
    CS_SHUTDOWN = 'CSShutdown'


class Client:
    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.format = None 
        self.name = f'{addr[0]}:{addr[1]}'
        self.buffer = b''  # 수신 데이터 버퍼
        self.lock = threading.Lock()  # 메시지 순서 보장을 위한 락
        # Protobuf 상태 추적
        self.protobuf_state = {
            'expecting_type': True,  # Type 메시지인지 데이터 메시지인지
            'current_type': None,    # 현재 처리 중인 Protobuf 메시지 타입
        }


class Room:
    def __init__(self, room_id, title):
        self.room_id = room_id
        self.title = title
        self.members = []


class ChatServer:
    def __init__(self, ip, port, num_workers, format):
        self.ip = ip
        self.port = port
        self.format = format

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.bind((ip, port))
        self.server_sock.listen(5)
        self.server_sock.setblocking(False)

        self.clients = {}  # 소켓 -> Client 객체
        self.rooms = {}    # room_id -> Room 객체
        self.client_rooms = {}  # 소켓 -> room_id

        self.num_workers = num_workers

        self.clients_lock = threading.Lock()
        self.rooms_lock = threading.Lock()

        self.message_queue = queue.Queue()
        self.condition = threading.Condition()

        self.running = True
        self.workers = []

        # 메시지 핸들러 맵
        self.json_handlers = {
            "CSName": self.handle_cs_name,
            "CSRooms": self.handle_cs_rooms,
            "CSCreateRoom": self.handle_cs_create_room,
            "CSJoinRoom": self.handle_cs_join_room,
            "CSLeaveRoom": self.handle_cs_leave_room,
            "CSChat": self.handle_cs_chat,
            "CSShutdown": self.handle_cs_shutdown,
        }
        self.protobuf_handlers = {
            pb.Type.MessageType.CS_NAME: self.handle_cs_name,
            pb.Type.MessageType.CS_ROOMS: self.handle_cs_rooms,
            pb.Type.MessageType.CS_CREATE_ROOM: self.handle_cs_create_room,
            pb.Type.MessageType.CS_JOIN_ROOM: self.handle_cs_join_room,
            pb.Type.MessageType.CS_LEAVE_ROOM: self.handle_cs_leave_room,
            pb.Type.MessageType.CS_CHAT: self.handle_cs_chat,
            pb.Type.MessageType.CS_SHUTDOWN: self.handle_cs_shutdown,
        }

    def start(self):
        # 워커 스레드 시작
        for _ in range(self.num_workers):
            worker = threading.Thread(target=self.worker_thread, daemon=True)
            worker.start()
            self.workers.append(worker)

        print(f"Server running on {self.ip}:{self.port}")

        try:
            while self.running:
                with self.clients_lock:
                    sockets = [self.server_sock] + [client.sock for client in self.clients.values()]
                readable, _, _ = select.select(sockets, [], [], 1)

                if not self.running:
                    break

                for sock in readable:
                    if sock == self.server_sock:
                        self.accept_new_connection()
                    else:
                        self.handle_client_data(sock)
        except KeyboardInterrupt:
            print("Server shutting down...")
            self.running = False
            with self.condition:
                self.condition.notify_all()
            for worker in self.workers:
                worker.join()

    def accept_new_connection(self):
        try:
            client_sock, client_addr = self.server_sock.accept()
            client_sock.setblocking(False)
            new_client = Client(client_sock, client_addr)
            with self.clients_lock:
                self.clients[client_sock] = new_client
                
            # 서버의 형식이 지정된 경우 클라이언트에 적용
            if self.format is not None:
                new_client.format = self.format

            print(f"새 클라이언트 연결됨: {new_client.name}")
        except Exception as e:
            print(f"새 연결 수락 오류: {e}")   

    def handle_client_data(self, sock):
        with self.clients_lock:
            client = self.clients.get(sock)
        if client:
            try:
                data = sock.recv(4096)
                if data:
                    with self.condition:
                        self.message_queue.put((client, data))
                        self.condition.notify()
                else:
                    self.remove_client(sock)
            except ConnectionError:
                self.remove_client(sock)
            except Exception as e:
                print(f"{client.name}로부터 데이터 수신 오류: {e}")
                self.remove_client(sock)

    def remove_client(self, sock):
        with self.clients_lock:
            client = self.clients.pop(sock, None)
        if client:
            print(f"Client {client.name} disconnected")
            with self.rooms_lock:
                room_id = self.client_rooms.pop(sock, None)
                if room_id:
                    room = self.rooms.get(room_id)
                    if room:
                        room.members.remove(client)
                        # 방에 있는 다른 멤버들에게 퇴장 메시지 전송
                        for member in room.members:
                            self.send_message(member, pb.SCSystemMessage(text=f"[{client.name}] 님이 퇴장했습니다."))
                        # 방에 멤버가 없으면 방 삭제
                        if not room.members:
                            del self.rooms[room_id]
            sock.close()

    def worker_thread(self):
        while self.running:
            with self.condition:
                while self.message_queue.empty() and self.running:
                    self.condition.wait()
                if not self.running:
                    break
                client, data = self.message_queue.get()

            # 클라이언트별 락을 획득하여 메시지 순서 보장
            with client.lock:
                self.process_data(client, data)

    def process_data(self, client, data):
        client.buffer += data
        while True:
            if len(client.buffer) < 2:
                break  # 메시지 길이를 알 수 없음
            message_length = int.from_bytes(client.buffer[:2], byteorder='big')
            if len(client.buffer) < 2 + message_length:
                break  # 전체 메시지를 아직 받지 못함
            message_data = client.buffer[2:2 + message_length]
            client.buffer = client.buffer[2 + message_length:]

            if client.format is None:
                # 클라이언트의 형식을 감지하거나 서버의 형식으로 설정
                if self.format is None:
                    self.detect_client_format(client, message_data)
                else:
                    client.format = self.format
                    # 서버의 형식으로 메시지 처리
                    if client.format == 'json':
                        self.process_json_message(client, message_data)
                    elif client.format == 'protobuf':
                        self.process_protobuf_message(client, message_data)
            else:
                # 이미 형식이 설정된 경우 해당 형식에 맞게 처리
                if client.format == 'json':
                    self.process_json_message(client, message_data)
                elif client.format == 'protobuf':
                    self.process_protobuf_message(client, message_data)

    def detect_client_format(self, client, data):
        # 먼저 JSON으로 시도
        try:
            message = json.loads(data.decode())
            if 'type' in message:
                client.format = 'json'
                print(f"클라이언트 {client.name}이 JSON 형식으로 감지됨")
                self.process_json_message(client, data)
                return
        except json.JSONDecodeError:
            pass  # JSON으로 파싱 실패, Protobuf로 시도

        # Protobuf로 시도
        try:
            type_message = pb.Type()
            type_message.ParseFromString(data)
            if type_message.type in self.protobuf_handlers:
                client.format = 'protobuf'
                client.protobuf_state['expecting_type'] = False
                client.protobuf_state['current_type'] = type_message.type
                print(f"클라이언트 {client.name}이 Protobuf 형식으로 감지됨 (타입: {type_message.type})")
                return
            else:
                print(f"알 수 없는 Protobuf 메시지 타입")
        except Exception as e:
            print(f"{client.name}로부터 JSON 또는 Protobuf 파싱 실패: {e}")

        # 포맷 감지 실패
        print(f"포맷 감지 실패. 클라이언트 연결 해제")
        self.send_system_message(client, "잘못된 메시지 형식. 연결 해제")
        self.remove_client(client.sock)

    def process_json_message(self, client, data):
        try:
            message = json.loads(data.decode())
            msg_type = message.get("type")

            handler = self.json_handlers.get(msg_type)
            if handler:
                handler(client, message)
            else:
                print(f"알 수 없는 JSON 메시지 타입")
                self.send_system_message(client, "Unknown command.")
        except json.JSONDecodeError as e:
            print(f"JSON 디코드 오류: {e}")
            self.send_system_message(client, "Invalid JSON format")

    def process_protobuf_message(self, client, data):
        try:
            if client.protobuf_state['expecting_type']:
                # Type 메시지 처리
                type_message = pb.Type()
                type_message.ParseFromString(data)
                msg_type = type_message.type
                if msg_type in self.protobuf_handlers:
                    client.protobuf_state['current_type'] = msg_type
                    client.protobuf_state['expecting_type'] = False
                else:
                    print(f"알 수 없는 Protobuf 메시지 타입: {msg_type}")
                    self.send_system_message(client, "Unknown Protobuf command.")
            else:
                # 실제 메시지 처리
                msg_type = client.protobuf_state['current_type']
                handler = self.protobuf_handlers.get(msg_type)
                if handler:
                    if msg_type == pb.Type.MessageType.CS_NAME:
                        msg = pb.CSName()
                        msg.ParseFromString(data)
                        handler(client, {"name": msg.name})
                    elif msg_type == pb.Type.MessageType.CS_ROOMS:
                        handler(client)
                    elif msg_type == pb.Type.MessageType.CS_CREATE_ROOM:
                        msg = pb.CSCreateRoom()
                        msg.ParseFromString(data)
                        handler(client, {"title": msg.title})
                    elif msg_type == pb.Type.MessageType.CS_JOIN_ROOM:
                        msg = pb.CSJoinRoom()
                        msg.ParseFromString(data)
                        handler(client, {"roomId": msg.roomId})
                    elif msg_type == pb.Type.MessageType.CS_LEAVE_ROOM:
                        handler(client)
                    elif msg_type == pb.Type.MessageType.CS_CHAT:
                        msg = pb.CSChat()
                        msg.ParseFromString(data)
                        handler(client, {"text": msg.text})
                    elif msg_type == pb.Type.MessageType.CS_SHUTDOWN:
                        handler(client)
                else:
                    print(f"Protobuf 메시지 타입에 대한 핸들러 없음: {msg_type}")
                    self.send_system_message(client, "Unknown Protobuf command.")
                # 다음 메시지는 Type 메시지로 예상
                client.protobuf_state['expecting_type'] = True
                client.protobuf_state['current_type'] = None
        except Exception as e:
            print(f"Protobuf 메시지 파싱 오류: {e}")
            self.send_system_message(client, "Invalid Protobuf message format")

    # 메시지 핸들러들
    def handle_cs_name(self, client, message):
        # 이름 변경 처리
        new_name = message.get("name", client.name)
        old_name = client.name
        client.name = new_name

        # 시스템 메시지 작성
        system_message = f"이름이 {new_name}으로 변경되었습니다."

        # 클라이언트가 방에 속해있는 경우 방의 모든 멤버에게 시스템 메시지 전송
        room_id = self.client_rooms.get(client.sock)
        if room_id is not None:
            room = self.rooms.get(room_id)
            if room:
                # 방에 있는 모든 멤버에게 이름 변경 메시지를 전송
                for member in room.members:
                    self.send_system_message(member, system_message)
        else:
            # 방에 속해 있지 않은 경우 클라이언트 본인에게만 메시지 전송
            self.send_system_message(client, system_message)

    def handle_cs_rooms(self, client, message=None):
        with self.rooms_lock:
            rooms_info = [pb.RoomInfo(roomId=room.room_id, title=room.title, members=room_members(room)) for room in self.rooms.values()]
        rooms_result = pb.SCRoomsResult()
        rooms_result.rooms.extend(rooms_info)
        self.send_message(client, rooms_result)

    def handle_cs_create_room(self, client, message):
        if self.client_rooms.get(client.sock) is not None:
            self.send_system_message(client, "대화방에 있을 때는 방을 개설할 수 없습니다.")
            return

        title = message.get("title", "Untitled Room")
        with self.rooms_lock:
            room_id = len(self.rooms) + 1
            room = Room(room_id, title)
            room.members.append(client)
            self.rooms[room_id] = room
            self.client_rooms[client.sock] = room_id  # 클라이언트를 생성된 방에 자동 입장시킴
        self.send_system_message(client, f"방제[{title}] 방에 입장했습니다.")

    def handle_cs_join_room(self, client, message):
        if self.client_rooms.get(client.sock) is not None:
            self.send_system_message(client, "대화방에 있을 때는 다른 방에 들어갈 수 없습니다.")
            return

        # 요청한 방이 존재하는지 확인 후 입장 처리
        room_id = message.get("roomId")
        with self.rooms_lock:
            room = self.rooms.get(room_id)
            if room:
                room.members.append(client)
                self.client_rooms[client.sock] = room_id  # 클라이언트를 해당 방에 입장시킴
                self.send_system_message(client, f"방제[{room.title}] 방에 입장했습니다.")
                # 다른 방 멤버들에게 입장 메시지 전송
                for member in room.members:
                    if member != client:
                        self.send_message(member, pb.SCSystemMessage(text=f"[{client.name}] 님이 입장했습니다."))
            else:
                self.send_system_message(client, "대화방이 존재하지 않습니다.")

    def handle_cs_leave_room(self, client, message=None):
        # 현재 방에 참여 중이지 않은 경우
        if self.client_rooms.get(client.sock) is None:
            self.send_system_message(client, "현재 대화방에 들어가 있지 않습니다.")
            return

        # 방에서 퇴장 처리
        with self.rooms_lock:
            room_id = self.client_rooms.pop(client.sock)
            room = self.rooms.get(room_id)
            if room:
                if client in room.members:
                    room.members.remove(client)
                    self.send_system_message(client, f"방제[{room.title}] 대화 방에서 퇴장했습니다.")
                    # 다른 방 멤버들에게 퇴장 메시지 전송
                    for member in room.members:
                        self.send_message(member, pb.SCSystemMessage(text=f"[{client.name}] 님이 퇴장했습니다."))
                # 방에 멤버가 없으면 방 삭제
                if not room.members:
                    del self.rooms[room_id]

    def handle_cs_chat(self, client, message):
        text = message.get("text")
        room_id = self.client_rooms.get(client.sock)

        # 클라이언트가 대화방에 없는 경우 시스템 메시지 전송
        if room_id is None:
            self.send_system_message(client, "현재 대화방에 들어가 있지 않습니다.")
            return

        # 클라이언트가 대화방에 있는 경우 메시지 브로드캐스트
        with self.rooms_lock:
            room = self.rooms.get(room_id)
            if room:
                self.broadcast_message(room, client, text)

    def broadcast_message(self, room, client, text):
        chat_message = pb.SCChat()
        chat_message.member = client.name
        chat_message.text = text
        for member in room.members:
            if member != client:
                self.send_message(member, chat_message)

    def handle_cs_shutdown(self, client=None, message=None):
        self.running = False
        self.server_sock.close()
        print("Server shutdown complete.")
        with self.condition:
            self.condition.notify_all()

    def send_system_message(self, client, text):
        system_message = pb.SCSystemMessage()
        system_message.text = text
        self.send_message(client, system_message)

    def send_message(self, client, message):
        try:
            if client.format == 'json':
                if isinstance(message, pb.SCRoomsResult):
                    # Convert Protobuf to dict
                    message_dict = {
                        "type": "SCRoomsResult",
                        "rooms": [
                            {
                                "roomId": room.roomId,
                                "title": room.title,
                                "members": room.members
                            } for room in message.rooms
                        ]
                    }
                elif isinstance(message, pb.SCChat):
                    message_dict = {
                        "type": "SCChat",
                        "member": message.member,
                        "text": message.text
                    }
                elif isinstance(message, pb.SCSystemMessage):
                    message_dict = {
                        "type": "SCSystemMessage",
                        "text": message.text
                    }
                else:
                    print("지원하지 않는 JSON 메시지 타입")
                    return

                # JSON 형식 메시지를 인코딩하여 전송
                encoded_message = json.dumps(message_dict).encode()

                # 메시지 길이를 2바이트로 변환하여 메시지 앞에 추가
                message_length = len(encoded_message)
                length_header = message_length.to_bytes(2, byteorder='big')

                # 길이 정보와 메시지를 함께 전송
                client.sock.sendall(length_header + encoded_message)

            elif client.format == 'protobuf':
                # Protobuf 타입 메시지 결정
                if isinstance(message, pb.SCRoomsResult):
                    type_message = pb.Type()
                    type_message.type = pb.Type.MessageType.SC_ROOMS_RESULT
                elif isinstance(message, pb.SCChat):
                    type_message = pb.Type()
                    type_message.type = pb.Type.MessageType.SC_CHAT
                elif isinstance(message, pb.SCSystemMessage):
                    type_message = pb.Type()
                    type_message.type = pb.Type.MessageType.SC_SYSTEM_MESSAGE
                else:
                    print("지원하지 않는 Protobuf 메시지 타입")
                    return

                # 각 메시지 직렬화
                type_encoded = type_message.SerializeToString()
                data_encoded = message.SerializeToString()

                # 길이 정보 추가
                type_length = len(type_encoded).to_bytes(2, byteorder='big')
                data_length = len(data_encoded).to_bytes(2, byteorder='big')

                # 타입 메시지 전송
                client.sock.sendall(type_length + type_encoded)

                # 실제 데이터 메시지 전송
                client.sock.sendall(data_length + data_encoded)
        except Exception as e:
            print(f"{client.name}에게 메시지 전송 오류: {e}")
            self.remove_client(client.sock)


def room_members(room):
    return [member.name for member in room.members]


def main():
    parser = argparse.ArgumentParser(description="Chat Server")
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--ip', type=str, default='127.0.0.1')
    parser.add_argument('--port', type=int, default=10125) 
    parser.add_argument('--format', type=str, choices=['json', 'protobuf'])

    args = parser.parse_args()

    server = ChatServer(ip=args.ip, port=args.port, num_workers=args.workers, format=args.format)
    server.start()


if __name__ == "__main__":
    main()
