#include <cstring>
#include <cstdio>
#include <iostream>
#include <unistd.h>

#include "open_addr_hashtable.hpp"

extern "C" int LLVMFuzzerTestOneInput(const uint8_t * Data, size_t size) {
  open_addr_hashtable<4096> hash;
  int i = 0;
  while (i < size) {
    switch (Data[i]) {
    case 'G':
      i++;
      if (i + sizeof(void *) < size) {
	printf("GET %ld\n", (long) Data[i]);
	hash.get((void *) &Data[i]);	
	i += sizeof(void *);
      } else {
	i = size;
      }
      break;
    case 'P':
      i++;
      if (i + 2 * sizeof(void *) < size) {
	printf("PUT %ld %ld\n", (long) Data[i], (long) Data[i+sizeof(void *)]);
	hash.put((void *) &Data[i], (void *) &Data[i+sizeof(void *)]);
	i += 2 * sizeof(void *);
      } else {
	i = size;
      }
      break;
    case 'R':
      i++;
      if (i + sizeof(void *) < size) {
	hash.remove((void *) &Data[i]);
	i += sizeof(void *);
      } else {
	i = size;
      }
    default:
      i++;
      break;
    }
  }
  return 0;
}

#if 1
int
main(int argc, char * argv[])
{
  char data[4096];
  memset(data, 0, 4096);
  read(0, data, 4096);
  auto result = fread(data, 4096, 1, stdin);
  if (result == 0) {
    printf("TESTING\n");
    LLVMFuzzerTestOneInput((const uint8_t *) data, strlen(data));
  }
  return 0;
}
#endif
