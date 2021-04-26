#include <cstring>
#include <cstdio>
#include <iostream>
#include <unistd.h>

#include "stprintf.h"

extern "C" int LLVMFuzzerTestOneInput(const uint8_t * Data, size_t size) {
#if 0
  if ((Data[0] == 'a') && (Data[size-1] == 'b')) {
    abort();
  }
  return 0;
#else
  const int BUFSIZE = 32768;
  char buf[BUFSIZE];
  char str[BUFSIZE];
  int i = 0;
  for (; (i < size) && (i < 4096); i++) {
    str[i] = Data[i];
  }
  //  printf("i = %d\n", i);
  //  printf("size = %d\n", size);
  str[i] = '\0';
  //  printf("str = %s\n", str);
  //stprintf::stprintf(buf, str, 42); // , "hello", 'a', 3.4);
  stprintf::stprintf(buf, str, BUFSIZE-1, 42, "hello", 'a', 3.4);
  printf("buf = %s\n", buf);
  return 0;
#endif
}

#if 1
int
main(int argc, char * argv[])
{
  char data[4096];
  //  stprintf::stprintf(data, "yo @, @, @, @\n", 4096, 42, "hello", 'a', 3.4);
  //  printf("data = %s\n", data);
  
  //  stprintf::stprintf(data, "hey @\n", 12);
  //  printf("data = %s\n", data);
  //  stprintf::stprintf(data, "hey @ @\n", 12, 3.4);
  //  printf("data = %s\n", data);
  memset(data, 0, 4096);
  read(0, data, 4096);
  auto result = fread(data, 4096, 1, stdin);
  if (result == 0) {
    //  printf("data = %s\n", data);
    LLVMFuzzerTestOneInput((const uint8_t *) data, strlen(data));
  }
  return 0;
}
#endif
