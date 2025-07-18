#include <chrono>
#include <iostream>
#include <thread>
#include <mutex>

using namespace std;

int sum = 0;
mutex m;

void f() {
    for (int i = 0; i < 10 * 1000 * 1000; ++i) {
        unique_lock<mutex> ul(m);
        ++sum;
    }
}
int main() {
    thread t(f);
    for (int i = 0; i < 10 * 1000 * 1000; ++i) {
        unique_lock<mutex> ul(m);
        ++sum;
    }
    t.join();
    cout << "Sum: " << sum << endl;
}
