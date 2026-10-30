#include <stdio.h>
#define M 32768
static int v[M];
int main(int argc, char **argv) {
    (void)argv;
    int reps = 3000 + argc - 1;
    unsigned s = 12345u;
    for (int i = 0; i < M; i++) { s = s * 1103515245u + 12345u; v[i] = (int)((s >> 8) % 1000) - 500; }
    long long sum = 0; int mn = v[0], mx = v[0], pos = 0;
    for (int r = 0; r < reps; r++) {
        for (int i = 0; i < M; i++) {
            sum += v[i] - r;
            if (v[i] < mn) mn = v[i];
            if (v[i] > mx) mx = v[i];
            pos += v[i] > 0;
        }
    }
    printf("%lld %d %d %d\n", sum, mn, mx, pos);
    return 0;
}
