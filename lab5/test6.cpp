#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <string.h>
#include <unistd.h>
#include <iostream>
#include <string>
#include "person.pb.h"  

using namespace std;
using namespace mju;

int main() {
    // Person 객체 생성 및 직렬화
    Person *p = new Person;
    p->set_name("MJ Kim");
    p->set_id(12345678);

    Person::PhoneNumber *phone = p->add_phones();
    phone->set_number("010-111-1234");
    phone->set_type(Person::MOBILE);

    phone = p->add_phones();
    phone->set_number("02-100-1000");
    phone->set_type(Person::HOME);

    const string s = p->SerializeAsString();
    cout << "Length:" << s.length() << endl;
    cout << s << endl;

    // UDP 소켓 생성
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0) {
        cerr << "소켓 생성 실패" << endl;
        return 1;
    }

    struct sockaddr_in server_addr;
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(10001);  // UDP 서버 포트 번호
    server_addr.sin_addr.s_addr = inet_addr("127.0.0.1");  // 로컬 서버 IP

    // 서버로 직렬화된 데이터 전송
    int numBytes = sendto(sock, s.c_str(), s.length(), 0, (struct sockaddr*) &server_addr, sizeof(server_addr));
    if (numBytes < 0) {
        cerr << "데이터 전송 실패" << endl;
        close(sock);
        return 1;
    }
    cout << "보낸 데이터 크기: " << numBytes << " bytes" << endl;

    // 서버로부터 데이터 수신
    char buffer[65536];
    socklen_t addr_len = sizeof(server_addr);
    numBytes = recvfrom(sock, buffer, sizeof(buffer), 0, (struct sockaddr*) &server_addr, &addr_len);
    if (numBytes < 0) {
        cerr << "데이터 수신 실패" << endl;
        close(sock);
        return 1;
    }
    cout << "수신한 데이터 크기: " << numBytes << " bytes" << endl;

    // 수신한 데이터를 역직렬화하여 p2 객체에 저장
    Person *p2 = new Person;
    if (p2->ParseFromArray(buffer, numBytes)) {  // 역직렬화
        cout << "Name:" << p2->name() << endl;
        cout << "ID:" << p2->id() << endl;
        for (int i = 0; i < p2->phones_size(); ++i) {
            cout << "Type:" << p2->phones(i).type() << endl;
            cout << "Phone:" << p2->phones(i).number() << endl;
        }
    } else {
        cerr << "역직렬화 실패" << endl;
    }

    close(sock);
    delete p;
    delete p2;

    return 0;
}
