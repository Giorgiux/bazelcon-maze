package engine;

import java.util.ArrayList;
import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.Deque;
import java.util.List;
import java.util.Random;

/**
 * Core engine for the maze game: level models, a seeded maze-carving algorithm,
 * and dependency-free JSON serialization. Generation is seeded via {@link Random}
 * (portable across JVMs), so a given seed always yields the same level.
 */
public final class Engine {

  private Engine() {}

  /** A generated maze level. Coordinates are [x, y] = [column, row]. */
  public static final class Level {
    public final int width;
    public final int height;
    /** grid[row][col]: 0 = open, 1 = wall. */
    public final int[][] grid;
    public final int[] start;
    public final int[] exit;
    public final List<int[]> keys;

    Level(int width, int height, int[][] grid, int[] start, int[] exit, List<int[]> keys) {
      this.width = width;
      this.height = height;
      this.grid = grid;
      this.start = start;
      this.exit = exit;
      this.keys = keys;
    }
  }

  /**
   * Carves a maze with a seeded iterative recursive-backtracker. Dimensions are
   * forced odd so the carve has clean wall/passage alternation.
   *
   * @param seed deterministic seed
   * @param width requested width (>= 5, forced odd)
   * @param height requested height (>= 5, forced odd)
   * @param numKeys collectibles to scatter on open cells
   */
  public static Level generate(long seed, int width, int height, int numKeys) {
    int w = toOdd(Math.max(5, width));
    int h = toOdd(Math.max(5, height));

    int[][] grid = new int[h][w];
    for (int[] row : grid) {
      Arrays.fill(row, 1);
    }

    Random rng = new Random(seed);
    boolean[][] visited = new boolean[h][w];
    int[][] dirs = {{-2, 0}, {2, 0}, {0, -2}, {0, 2}};

    int sr = 1;
    int sc = 1;
    grid[sr][sc] = 0;
    visited[sr][sc] = true;

    Deque<int[]> stack = new ArrayDeque<>();
    stack.push(new int[] {sr, sc});

    while (!stack.isEmpty()) {
      int[] cur = stack.peek();
      List<int[]> candidates = new ArrayList<>();
      for (int[] d : dirs) {
        int nr = cur[0] + d[0];
        int nc = cur[1] + d[1];
        if (nr > 0 && nr < h - 1 && nc > 0 && nc < w - 1 && !visited[nr][nc]) {
          candidates.add(new int[] {nr, nc, d[0], d[1]});
        }
      }
      if (candidates.isEmpty()) {
        stack.pop();
        continue;
      }
      int[] pick = candidates.get(rng.nextInt(candidates.size()));
      grid[cur[0] + pick[2] / 2][cur[1] + pick[3] / 2] = 0;
      grid[pick[0]][pick[1]] = 0;
      visited[pick[0]][pick[1]] = true;
      stack.push(new int[] {pick[0], pick[1]});
    }

    int[] start = {sc, sr};
    int[] exit = {w - 2, h - 2};
    List<int[]> keys = scatterKeys(grid, w, h, numKeys, start, exit, rng);

    return new Level(w, h, grid, start, exit, keys);
  }

  private static List<int[]> scatterKeys(
      int[][] grid, int w, int h, int numKeys, int[] start, int[] exit, Random rng) {
    List<int[]> open = new ArrayList<>();
    for (int r = 1; r < h - 1; r++) {
      for (int c = 1; c < w - 1; c++) {
        boolean isStart = (c == start[0] && r == start[1]);
        boolean isExit = (c == exit[0] && r == exit[1]);
        if (grid[r][c] == 0 && !isStart && !isExit) {
          open.add(new int[] {c, r});
        }
      }
    }
    // Deterministic shuffle, then take the first numKeys cells.
    for (int i = open.size() - 1; i > 0; i--) {
      int j = rng.nextInt(i + 1);
      int[] tmp = open.get(i);
      open.set(i, open.get(j));
      open.set(j, tmp);
    }
    List<int[]> keys = new ArrayList<>();
    int n = Math.min(numKeys, open.size());
    for (int i = 0; i < n; i++) {
      keys.add(open.get(i));
    }
    return keys;
  }

  private static int toOdd(int n) {
    return (n % 2 == 0) ? n + 1 : n;
  }

  /** Serializes a level to compact JSON. No external dependencies. */
  public static String toJson(Level level, String name) {
    StringBuilder sb = new StringBuilder(1024);
    sb.append('{');
    sb.append("\"name\":\"").append(escape(name)).append("\",");
    sb.append("\"width\":").append(level.width).append(',');
    sb.append("\"height\":").append(level.height).append(',');
    sb.append("\"start\":").append(point(level.start)).append(',');
    sb.append("\"exit\":").append(point(level.exit)).append(',');
    sb.append("\"keys\":[");
    for (int i = 0; i < level.keys.size(); i++) {
      if (i > 0) {
        sb.append(',');
      }
      sb.append(point(level.keys.get(i)));
    }
    sb.append("],");
    sb.append("\"grid\":[");
    for (int r = 0; r < level.height; r++) {
      if (r > 0) {
        sb.append(',');
      }
      sb.append('[');
      for (int c = 0; c < level.width; c++) {
        if (c > 0) {
          sb.append(',');
        }
        sb.append(level.grid[r][c]);
      }
      sb.append(']');
    }
    sb.append("]}");
    return sb.toString();
  }

  private static String point(int[] p) {
    return "[" + p[0] + "," + p[1] + "]";
  }

  private static String escape(String s) {
    return s.replace("\\", "\\\\").replace("\"", "\\\"");
  }
}
