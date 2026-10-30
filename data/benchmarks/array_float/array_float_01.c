#include <stdio.h>
#define M 4096
static float a[M], b[M];
int main(int argc, char **argv) {
    (void)argv;
    int reps = 40000 + argc - 1;
    for (int i = 0; i < M; i++) { a[i] = (float)(i % 17) * 0.5f; b[i] = (float)(i % 13); }
    for (int r = 0; r < reps; r++)
        for (int i = 0; i < M; i++) b[i] = b[i] * 0.999f + a[i] * 0.01f;
    double s = 0.0;
    for (int i = 0; i < M; i++) s += b[i];
    printf("%.3f\n", s);
    return 0;
}
