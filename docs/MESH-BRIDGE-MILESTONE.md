# Future milestone: independent Meshtastic bridge (`task-mesh-bridge`)

> **Status:** a future, non-blocking milestone. The public experimental alpha does not include this work, and it is **not validated on a physical Raspberry Pi**.

**Status:** proposed, not scheduled, not started. The public alpha ships
T.A.S.K. Mesh exactly as it is today: meshtastic in-process, the package
under GPL-3.0. The working Mesh service on the Pi (0.3.1) and its custom
notifications are not touched by this plan.

**Why do it at all?** Under Option A, everything is GPL anyway, so a bridge
isn't needed for licensing today. It is worth considering later for two reasons:
* **Engineering:** it isolates the library's blocking calls, global pubsub
  state and crashes in their own process.
* **Optional licensing flexibility:** it keeps open a separate license for the
  Mesh app later (for example a commercial license for custom deployments),
  if you ever want that.

A fuller internal analysis was prepared during the license review. It is
not part of this public tree.

## Scope
1. **Protocol (TRLP v1).** A documented, versioned protocol of JSON lines
   over a Unix socket (`$XDG_RUNTIME_DIR/task/…`) or stdio.
   * It starts with a `hello`/capabilities exchange.
   * Commands: connect, close, identity, nodes, channels, send_text, heartbeat.
   * Events: link, identity, node, observation, text, delivery, notice, error.
   * It uses **T.A.S.K.'s own vocabulary** (from `domain/models.py`). It never
     carries Meshtastic protobuf names, protobuf bytes or library objects.
2. **Separate GPL-3.0 program.**
   * `task-mesh-bridge` is the only code that imports meshtastic, pubsub or
     protobuf.
   * It is its own Debian package, with its own LICENSE and its own source.
   * It is usable on its own through `--stdio`.
   * The Mesh app only `Suggests` it.
   * It takes over today's 5 adapter files (about 700 lines), plus the active
     Meshtastic probe query and the Meshtastic field parsing.
3. **App side.** A `BridgeClientProvider` implements the existing
   `RadioProvider`/sink contract. Without the bridge, the app still runs:
   MeshCore and the mock keep working, and the app says "Meshtastic support
   not installed".
4. **MeshCore compatibility.** The MeshCore adapter (MIT) stays in-process
   and unchanged. The protocol is designed so a MeshCore radio could be
   described the same way.

## Things the bridge does not do
* **It doesn't automatically end GPL obligations.** Separating processes
  doesn't by itself make two programs separate works. The FSF looks at both
  the mechanism and how "intimate" the communication is. The bridge is
  always GPL, and an attorney has to review whether the app is then a
  separate work.
* **It doesn't change licenses already granted.** Every version released
  under the GPL stays GPL for its recipients.

## Decisions before the milestone starts
* **CLA vs DCO for `mesh/`.** Separate app terms later are only possible for
  code you own, or code contributed under a CLA. If you want that option,
  decide before outside contributions to `mesh/` arrive (REMAINING-DECISIONS #2).
* **Attorney review** of the protocol and the packaging.
* **The app's license after separation.** The simplest choice is to stay
  GPL-3.0-or-later.

## Effort and test plan (estimates, not measured)
* **Effort:** about 10–17 developer-days, plus attorney review.
* **Tests:**
  1. The current Mesh suite passes against a mock bridge.
  2. MeshCore fake scenarios pass, with the adapter unchanged.
  3. No-bridge mode works.
  4. Isolation: meshtastic, pubsub and protobuf never load in the app process,
     and the app contains no `.proto` or `*_pb2` files.
  5. TRLP conformance and fault tests.
  6. Packaging: no `Depends` on the bridge, and separate copyright files.
* **Hardware:** a Heltec V3 test on a spare SD card, receive-only first, then
  a single operator-initiated send, only with explicit approval.
  **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.**

## Not blocking
None of this is needed to publish the alpha. The alpha's licensing is
complete without it.
