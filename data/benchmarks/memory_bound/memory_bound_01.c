#include <stdio.h>
#define M 524288
static unsigned nxt[M];
static unsigned data[M];
int main(int argc, char **argv) {
    (void)argv;
    unsigned s = 3u + (unsigned)argc;
    for (unsigned i = 0; i < M; i++) { nxt[i] = i; data[i] = i * 2654435761u; }
    for (unsigned i = M - 1; i > 0; i--) { s = s * 1103515245u + 12345u; unsigned j = (s >> 8) % i; unsigned t = nxt[i]; nxt[i] = nxt[j]; nxt[j] = t; }
    unsigned p = 0; unsigned long long acc = 0;
    long steps = 2000000 + argc - 1;
    for (long i = 0; i < steps; i++) { p = nxt[p]; acc += data[p]; }
    unsigned long long strided = 0;
    for (int r = 0; r < 4; r++) for (unsigned i = 0; i < M; i += 16) strided += data[i];
    printf("%llu %llu\n", acc, strided);
    return 0;
}
