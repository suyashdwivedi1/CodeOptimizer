#include <stdio.h>
#include <stdlib.h>
#define N 12000
static int v[N];
int main(int argc, char **argv) {
    (void)argv;
    unsigned s = 99u + (unsigned)argc;
    for (int i = 0; i < N; i++) { s = s * 1103515245u + 12345u; v[i] = (int)((s >> 10) % 100000); }
    for (int i = 1; i < N; i++) { int key = v[i]; int j = i - 1; while (j >= 0 && v[j] > key) { v[j + 1] = v[j]; j--; } v[j + 1] = key; }
    long long chk = 0;
    for (int i = 0; i < N; i++) chk = chk * 31 + v[i];
    printf("%d %d %lld\n", v[0], v[N - 1], chk);
    return 0;
}
