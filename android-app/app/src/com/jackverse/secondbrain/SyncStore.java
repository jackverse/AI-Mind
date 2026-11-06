package com.jackverse.secondbrain;

import java.io.IOException;
import java.util.Set;

/** GitHub 同步只依赖这几个读写动作，方便在电脑上单测。 */
public interface SyncStore {
    byte[] read(String path) throws IOException;

    void write(String path, byte[] data) throws IOException;

    void prune(Set<String> keep) throws IOException;
}
