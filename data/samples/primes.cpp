// C++ prime sieve with std::vector
#include <cstdio>
#include <vector>
int main(int argc, char **argv) {
    (void)argv;
    const int N = 5000000 + argc;
    std::vector<char> sieve(N + 1, 1);
    long count = 0;
    for (int i = 2; i <= N; i++) {
        if (sieve[i]) { count++; for (long j = (long)i * i; j <= N; j += i) sieve[j] = 0; }
    }
    std::printf("%ld\n", count);
    return 0;
}
