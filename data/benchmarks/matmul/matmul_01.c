#include <stdio.h>
#define N 300
typedef double T;
static T A[N][N], B[N][N], C[N][N];
int main(int argc, char **argv) {
    (void)argv;
    for (int i = 0; i < N; i++) for (int j = 0; j < N; j++) { A[i][j] = (T)((i * 7 + j * 3 + argc) % 11); B[i][j] = (T)((i * 5 + j * 2) % 13); C[i][j] = 0; }
    for (int i = 0; i < N; i++) for (int j = 0; j < N; j++) { T acc = 0; for (int k = 0; k < N; k++) acc += A[i][k] * B[k][j]; C[i][j] = acc; }
    T tr = 0;
    for (int i = 0; i < N; i++) tr += C[i][i] + C[i][N - 1 - i];
    printf("%.4f\n", tr);
    return 0;
}
