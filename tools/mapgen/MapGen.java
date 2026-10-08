package tools.mapgen;

import engine.Engine;

/**
 * Thin CLI around {@link Engine}. Prints one level as JSON on stdout.
 *
 * <p>Usage: {@code mapgen <seed> <width> <height> [numKeys] [name]}
 */
public final class MapGen {

  private MapGen() {}

  public static void main(String[] args) {
    long seed = args.length > 0 ? Long.parseLong(args[0]) : 1L;
    int width = args.length > 1 ? Integer.parseInt(args[1]) : 15;
    int height = args.length > 2 ? Integer.parseInt(args[2]) : 15;
    int numKeys = args.length > 3 ? Integer.parseInt(args[3]) : 3;
    String name = args.length > 4 ? args[4] : "level";
    // Optional repeat count (default 1): regenerate the maze this many times.
    // Deterministic for a given seed; larger values do more generation work.
    int iterations = args.length > 5 ? Integer.parseInt(args[5]) : 1;

    Engine.Level level = null;
    for (int it = 0; it < iterations; it++) {
      level = Engine.generate(seed, width, height, numKeys);
    }
    System.out.println(Engine.toJson(level, name));
  }
}
