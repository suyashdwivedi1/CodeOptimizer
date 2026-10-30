#include <stdio.h>
#include <stdlib.h>
#define N 600000
static int v[N];
static int cmp(const void *a, const void *b) { int x = *(const int *)a, y = *(const int *)b; return (x > y) - (x < y); }
int main(int argc, char **argv) {
    (void)argv;
    unsigned s = 99u + (unsigned)argc;
    for (int i = 0; i < N; i++) { s = s * 1103515245u + 12345u; v[i] = (int)((s >> 10) % 100000); }
    qsort(v, N, sizeof(int), cmp);
    long long chk = 0;
    for (int i = 0; i < N; i++) chk = chk * 31 + v[i];
    printf("%d %d %lld\n", v[0], v[N - 1], chk);
    return 0;
}
