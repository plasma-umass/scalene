class Libscalene < Formula
  desc "Memory profiling library for the Scalene profiler for Python"
  homepage "https://github.com/emeryberger/scalene"

  head do
    url "https://github.com/emeryberger/scalene.git", :branch => "master"
  end

  def install
    inreplace "heaplayers-make.mk", /git clone https:\/\/github.com\/emeryberger\/Heap-Layers/, "/usr/bin/true"
    system "git", "clone", "https://github.com/emeryberger/Heap-Layers"
    system "make"

    lib.install "libscalene.dylib"
    
    (buildpath/"runner_script").write(runner_script)
    bin.install "runner_script" => "scalene"
  end
  
  def runner_script; <<-EOS
#!/usr/bin/env sh

DYLD_INSERT_LIBRARIES=#{lib}/libscalene.dylib PYTHONMALLOC=malloc python -m scalene "$@"
  EOS
  end

end
