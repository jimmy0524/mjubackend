#include <chrono>
#include <iostream>
#include <thread>
#include <mutex>

using namespace std;

int sum = 0;
mutex m;
mutex m2;

void f() {
    for (int i = 0; i < 10 * 1000 * 1000; ++i) {
        m.lock();
        m2.lock();
        ++sum;
        m2.unlock();
        m.unlock();
    }
}
int main() {
    thread t(f);
    for (int i = 0; i < 10 * 1000 * 1000; ++i) {
        m.lock();
        m2.lock();
        ++sum;
        m2.unlock();
        m.unlock();
    }
    t.join();
    cout << "Sum: " << sum << endl;
}
