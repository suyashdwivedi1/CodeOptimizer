// Matrix-vector product (vectorizable loops)
#include <stdio.h>
#define N 512
static float A[N][N], x[N], y[N];
int main(int argc, char **argv) {
    (void)argv;
    for (int i = 0; i < N; i++) { x[i] = (float)(i % 7) + argc; for (int j = 0; j < N; j++) A[i][j] = (float)((i * j) % 5); }
    for (int r = 0; r < 300; r++)
        for (int i = 0; i < N; i++) { float s = 0; for (int j = 0; j < N; j++) s += A[i][j] * x[j]; y[i] = s; }
    double t = 0; for (int i = 0; i < N; i++) t += y[i];
    printf("%.1f\n", t);
    return 0;
}
