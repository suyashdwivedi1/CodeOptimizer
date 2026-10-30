#include <stdio.h>
#define M 262144
static int arr[M];
static int find(int key) {
    int lo = 0, hi = M - 1;
    while (lo <= hi) {
        int mid = lo + (hi - lo) / 2;
        if (arr[mid] == key) return mid;
        if (arr[mid] < key) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
}
int main(int argc, char **argv) {
    (void)argv;
    for (int i = 0; i < M; i++) arr[i] = i * 5;
    unsigned s = 7u + (unsigned)argc; long hits = 0, idxsum = 0;
    long q = 500000 + argc - 1;
    for (long i = 0; i < q; i++) {
        s = s * 1664525u + 1013904223u;
        int r = find((int)((s >> 4) % (unsigned)(M * 5)));
        if (r >= 0) { hits++; idxsum += r; }
    }
    printf("%ld %ld\n", hits, idxsum);
    return 0;
}
