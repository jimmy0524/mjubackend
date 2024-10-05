#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <string.h>
#include <unistd.h>
#include <iostream>

using namespace std;

int main() {
    int s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s < 0) {
        cout << "Socket creation failed!" << endl;
        return 1;
    }

    struct sockaddr_in sin;
    memset(&sin, 0, sizeof(sin));
    sin.sin_family = AF_INET;
    sin.sin_port = htons(10125);
    sin.sin_addr.s_addr = inet_addr("127.0.0.1");

    if (bind(s, (struct sockaddr*)&sin, sizeof(sin)) < 0) {
        cout << "Bind failed!" << endl;
        close(s);
        return 1;
    }

    while (true) {
        cout << "Bind Success!" << endl;
        char buf[65536] = {0};
        struct sockaddr_in client_addr;
        socklen_t client_addr_len = sizeof(client_addr);

        int numBytes = recvfrom(s, buf, sizeof(buf), 0, 
                                (struct sockaddr*)&client_addr, &client_addr_len);
        if (numBytes > 0) {
            cout << "Received: " << buf << endl;
            cout << "From: " << inet_ntoa(client_addr.sin_addr) << endl;

            sendto(s, buf, numBytes, 0, (struct sockaddr*)&client_addr, client_addr_len);
        }
    }

    close(s);
    return 0;
}
