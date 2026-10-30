#include <stdio.h>
#define L 10000
static char buf[L + 1];
int main(int argc, char **argv) {
    (void)argv;
    unsigned s = 5u + (unsigned)argc;
    for (int i = 0; i < L; i++) { s = s * 1103515245u + 12345u; buf[i] = (char)('a' + (s >> 16) % 5); }
    buf[L] = 0;
    unsigned long h = 5381; long vowels = 0, runs = 0;
    int reps = 1500 + argc - 1;
    for (int r = 0; r < reps; r++) {
        for (int i = 0; i < L; i++) {
            char c = buf[i];
            h = ((h << 5) + h) + (unsigned char)c;
            switch (c) { case 'a': case 'e': case 'i': case 'o': case 'u': vowels++; break; default: break; }
            if (i > 0 && buf[i - 1] == c) runs++;
        }
    }
    printf("%lu %ld %ld\n", h, vowels, runs);
    return 0;
}
