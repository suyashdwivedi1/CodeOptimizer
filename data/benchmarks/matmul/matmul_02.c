#include <stdio.h>
#define N 256
typedef int T;
static T A[N][N], B[N][N], C[N][N];
int main(int argc, char **argv) {
    (void)argv;
    for (int i = 0; i < N; i++) for (int j = 0; j < N; j++) { A[i][j] = (T)((i * 7 + j * 3 + argc) % 11); B[i][j] = (T)((i * 5 + j * 2) % 13); C[i][j] = 0; }
    for (int i = 0; i < N; i++) for (int k = 0; k < N; k++) { T aik = A[i][k]; for (int j = 0; j < N; j++) C[i][j] += aik * B[k][j]; }
    T tr = 0;
    for (int i = 0; i < N; i++) tr += C[i][i] + C[i][N - 1 - i];
    printf("%lld\n", (long long)tr);
    return 0;
}
