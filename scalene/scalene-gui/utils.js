export function memory_consumed_str(size_in_mb) {
  // Return a string corresponding to amount of memory consumed.
  let gigabytes = Math.floor(size_in_mb / 1024);
  let terabytes = Math.floor(gigabytes / 1024);
  if (terabytes > 0) {
    return `${(size_in_mb / 1048576).toFixed(0)}T`;
  } else if (gigabytes > 0) {
    return `${(size_in_mb / 1024).toFixed(0)}G`;
  } else {
    return `${size_in_mb.toFixed(0)}M`;
  }
}

export function time_consumed_str(time_in_ms) {
  let hours = Math.floor(time_in_ms / 3600000);
  let minutes = Math.floor((time_in_ms % 3600000) / 60000);
  let seconds = Math.floor((time_in_ms % 60000) / 1000);
  let minutes_exact = (time_in_ms % 3600000) / 60000;
  let seconds_exact = (time_in_ms % 60000) / 1000;
  if (hours > 0) {
    return `${hours.toFixed(0)}h:${minutes_exact.toFixed(
      0,
    )}m:${seconds_exact.toFixed(3)}s`;
  } else if (minutes >= 1) {
    return `${minutes.toFixed(0)}m:${seconds_exact.toFixed(3)}s`;
  } else if (seconds >= 1) {
    return `${seconds_exact.toFixed(3)}s`;
  } else {
    return `${time_in_ms.toFixed(0)}ms`;
  }
}
