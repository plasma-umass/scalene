export function unescapeUnicode(s: string): string {
  return s.replace(/\\u([\dA-F]{4})/gi, function (_match, p1: string) {
    return String.fromCharCode(parseInt(p1, 16));
  });
}

export function countSpaces(str: string): number {
  // Use a regular expression to match any whitespace character at the start of the string
  const match = str.match(/^\s+/);

  // If there was a match, return the length of the match
  if (match) {
    return match[0].length;
  }

  // Otherwise, return 0
  return 0;
}

export function memory_consumed_str(size_in_mb: number): string {
  // Return a string corresponding to amount of memory consumed.
  const gigabytes = Math.floor(size_in_mb / 1024);
  const terabytes = Math.floor(gigabytes / 1024);
  if (terabytes > 0) {
    return `${(size_in_mb / 1048576).toFixed(0)}T`;
  } else if (gigabytes > 0) {
    return `${(size_in_mb / 1024).toFixed(0)}G`;
  } else {
    return `${size_in_mb.toFixed(0)}M`;
  }
}

export function time_consumed_str(time_in_ms: number): string {
  const hours = Math.floor(time_in_ms / 3600000);
  const minutes = Math.floor((time_in_ms % 3600000) / 60000);
  const seconds = Math.floor((time_in_ms % 60000) / 1000);
  const minutes_exact = (time_in_ms % 3600000) / 60000;
  const seconds_exact = (time_in_ms % 60000) / 1000;
  if (hours > 0) {
    return `${hours.toFixed(0)}h:${minutes_exact.toFixed(0)}m:${seconds_exact.toFixed(3)}s`;
  } else if (minutes >= 1) {
    return `${minutes.toFixed(0)}m:${seconds_exact.toFixed(3)}s`;
  } else if (seconds >= 1) {
    return `${seconds_exact.toFixed(3)}s`;
  } else {
    return `${time_in_ms.toFixed(0)}ms`;
  }
}
