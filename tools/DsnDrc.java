import app.freerouting.board.facade.BasicBoard;
import app.freerouting.board.model.items.DrillItem;
import app.freerouting.board.model.items.Item;
import app.freerouting.board.model.items.Pin;
import app.freerouting.board.model.structure.Unit;
import app.freerouting.board.trace.PolylineTrace;
import app.freerouting.drc.ClearanceViolation;
import app.freerouting.drc.DesignRulesChecker;
import app.freerouting.geometry.planar.FloatPoint;
import app.freerouting.geometry.planar.Point;
import app.freerouting.io.BoardReadResult;
import app.freerouting.io.specctra.DsnReader;
import app.freerouting.rules.Net;
import app.freerouting.settings.DesignRulesCheckerSettings;
import java.io.FileInputStream;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * Freerouting's own view of a DSN before any routing: its clearance violations, its incomplete connections, and
 * the nets whose pins the DSN's copper does not join even when a track end or via inside a pad, or within SNAP_UM of
 * another end, counts as joined. Freerouting joins a track to a pin only at the pin's exact centre, and
 * KiCad's export writes wire coordinates in whole micrometres (D130), so its own count reports every pre-laid
 * track as open. Used by scripts/translation_check.py.
 *
 * <p>java -cp freerouting.jar:. DsnDrc board.dsn
 */
public final class DsnDrc {

  static final double SNAP_UM = 1.0;

  private static String netName(BasicBoard board, Item item) {
    if (item.netCount() == 0) {
      return "-";
    }
    Net n = board.rules.nets.get(item.getNetNumber(0));
    return n != null ? n.name : "#" + item.getNetNumber(0);
  }

  private static String describe(BasicBoard board, Item item) {
    String kind = item.getClass().getSimpleName();
    if (item instanceof Pin pin) {
      kind = "Pin " + pin.componentName() + "-" + pin.name();
    }
    return kind + " [" + netName(board, item) + "]" + (item.isUserFixed() ? " fixed" : "");
  }

  private static int find(Map<Item, Item> parent, Item x) {
    Item root = x;
    while (parent.get(root) != root) {
      root = parent.get(root);
    }
    while (parent.get(x) != root) {
      Item next = parent.get(x);
      parent.put(x, root);
      x = next;
    }
    return root.getId();
  }

  private static void union(Map<Item, Item> parent, Item a, Item b) {
    Item ra = a;
    while (parent.get(ra) != ra) {
      ra = parent.get(ra);
    }
    Item rb = b;
    while (parent.get(rb) != rb) {
      rb = parent.get(rb);
    }
    if (ra != rb) {
      parent.put(ra, rb);
    }
  }

  private static boolean insidePad(BasicBoard board, Pin pin, int layer, FloatPoint point) {
    var tree = board.searchTreeManager.getDefaultTree();
    for (int i = 0; i < pin.treeShapeCount(tree); i++) {
      if (pin.shapeLayer(i) == layer && pin.getTreeShape(tree, i).contains(point)) {
        return true;
      }
    }
    return false;
  }

  private static boolean onLayer(Item item, int layer) {
    return item.firstLayer() <= layer && layer <= item.lastLayer();
  }

  public static void main(String[] args) throws Exception {
    BoardReadResult result =
        DsnReader.readBoard(new FileInputStream(args[0]), null, null, "translation-check");
    if (!(result instanceof BoardReadResult.Success success)) {
      System.out.println("DSN not loaded: " + result);
      System.exit(2);
      return;
    }
    BasicBoard board = success.board();
    double perMm = board.communication.getResolution(Unit.MM);
    double snap = SNAP_UM * perMm / 1000.0;
    DesignRulesChecker drc = new DesignRulesChecker(board, new DesignRulesCheckerSettings());
    Collection<ClearanceViolation> violations = drc.getAllClearanceViolations();
    int incomplete = drc.getIncompleteCount();

    // the nets the copper joins, with a track end within the snap of a pad centre, a via or another end joined
    int open = 0;
    List<String> openNets = new ArrayList<>();
    for (int net = 1; net <= board.rules.nets.maxNetNumber(); net++) {
      Collection<Item> items = board.getConnectableItems(net);
      List<Item> pins = new ArrayList<>();
      Map<Item, Item> parent = new HashMap<>();
      for (Item it : items) {
        parent.put(it, it);
        if (it instanceof Pin) {
          pins.add(it);
        }
      }
      if (pins.size() < 2) {
        continue;
      }
      for (Item it : items) {
        for (Item c : it.getNormalContacts()) {
          if (parent.containsKey(c)) {
            union(parent, it, c);
          }
        }
        // the points where this item meets others: a track's two ends, a via's centre on each of its layers
        List<Point> points = new ArrayList<>();
        List<Integer> layers = new ArrayList<>();
        if (it instanceof PolylineTrace t) {
          points.add(t.firstCorner());
          layers.add(t.getLayer());
          points.add(t.lastCorner());
          layers.add(t.getLayer());
        } else if (it instanceof DrillItem d && !(it instanceof Pin)) {
          for (int l = d.firstLayer(); l <= d.lastLayer(); l++) {
            points.add(d.getCenter());
            layers.add(l);
          }
        }
        for (int k = 0; k < points.size(); k++) {
          FloatPoint e = points.get(k).toFloat();
          int layer = layers.get(k);
          for (Item o : items) {
            if (o == it || !onLayer(o, layer)) {
              continue;
            }
            if (o instanceof DrillItem d && d.getCenter().toFloat().distance(e) <= snap) {
              union(parent, it, o);
            } else if (o instanceof Pin p && insidePad(board, p, layer, e)) {
              union(parent, it, o); // KiCad joins copper anywhere inside a pad
            } else if (o instanceof PolylineTrace u
                && u.getLayer() == layer
                && (u.firstCorner().toFloat().distance(e) <= snap
                    || u.lastCorner().toFloat().distance(e) <= snap)) {
              union(parent, it, o);
            }
          }
        }
      }
      java.util.Set<Integer> groups = new java.util.HashSet<>();
      for (Item p : pins) {
        groups.add(find(parent, p));
      }
      if (groups.size() > 1) {
        open++;
        openNets.add(board.rules.nets.get(net).name + " (" + groups.size() + " pieces)");
      }
    }

    Map<String, Integer> kinds = new TreeMap<>();
    for (ClearanceViolation v : violations) {
      String a = v.firstItem.getClass().getSimpleName();
      String b = v.secondItem.getClass().getSimpleName();
      String key =
          (a.compareTo(b) <= 0 ? a + "/" + b : b + "/" + a)
              + (netName(board, v.firstItem).equals(netName(board, v.secondItem)) ? " same net" : "")
              + " on "
              + board.layerStructure.layers[v.layer].name;
      kinds.merge(key, 1, Integer::sum);
    }
    System.out.println(
        "clearance violations: " + violations.size()
            + "; Freerouting's incomplete connections: " + incomplete
            + "; nets the copper leaves open (ends within " + SNAP_UM + " um joined): " + open);
    kinds.forEach((k, n) -> System.out.println(String.format("  %5d  %s", n, k)));
    for (String n : openNets) {
      System.out.println("OPEN " + n);
    }
    for (ClearanceViolation v : violations) {
      System.out.println(
          String.format(
              "VIOLATION %s | %s | layer %s | expected %.4f mm actual %.4f mm",
              describe(board, v.firstItem),
              describe(board, v.secondItem),
              board.layerStructure.layers[v.layer].name,
              v.expectedClearance / perMm,
              v.actualClearance / perMm));
    }
  }
}
