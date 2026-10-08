package tests;

import engine.Engine;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Stress test for the maze engine: runs many CPU-heavy generation and validation
 * cases.
 *
 * <p>It supports Bazel test sharding (set {@code shard_count} in BUILD.bazel) to
 * split the cases across parallel test processes. It reads TEST_TOTAL_SHARDS /
 * TEST_SHARD_INDEX and touches TEST_SHARD_STATUS_FILE as the shard protocol
 * requires, so it needs no test framework.
 */
public final class MazeStressTest {

  private MazeStressTest() {}

  // Number of cases, and generation passes per case.
  private static final int CASES = 24;
  private static final int ITERS = 2000;

  public static void main(String[] args) throws IOException {
    int total = envInt("TEST_TOTAL_SHARDS", 1);
    int index = envInt("TEST_SHARD_INDEX", 0);
    touchShardStatus();

    int ran = 0;
    for (int c = 0; c < CASES; c++) {
      if (total > 1 && c % total != index) {
        continue; // another shard owns this case
      }
      runCase(c);
      ran++;
    }
    System.out.println("shard " + index + "/" + total + " ran " + ran + " of " + CASES + " cases");
  }

  /** One heavy case: regenerate a maze many times and check basic invariants. */
  private static void runCase(int c) {
    Engine.Level level = null;
    for (int it = 0; it < ITERS; it++) {
      level = Engine.generate(100 + c, 61, 61, 5);
    }
    if (level.width <= 0 || level.height <= 0) {
      throw new AssertionError("case " + c + ": bad dimensions");
    }
    if (level.grid.length != level.height || level.grid[0].length != level.width) {
      throw new AssertionError("case " + c + ": grid shape mismatch");
    }
    // Start cell must be carved open.
    if (level.grid[level.start[1]][level.start[0]] != 0) {
      throw new AssertionError("case " + c + ": start cell is a wall");
    }
  }

  private static int envInt(String key, int fallback) {
    String v = System.getenv(key);
    return (v == null || v.isEmpty()) ? fallback : Integer.parseInt(v);
  }

  private static void touchShardStatus() throws IOException {
    String f = System.getenv("TEST_SHARD_STATUS_FILE");
    if (f != null && !f.isEmpty()) {
      Files.write(Path.of(f), new byte[0]);
    }
  }
}
