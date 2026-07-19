# ML C2S2 Dynamic Pick Timing

This is the required timing contract for the external ML node that computes
Robot2 dynamic C2S2 pick joints.

## Topics

Subscribe:

```text
/niryo_factory/status
```

Trigger only on:

```text
resource_id == "vision_robot2"
task == "CAPTURE_LOCAL_VISION"
resource_state == "SCANNING"
```

Publish:

```text
/robot2/pick_joints_c2s2
```

Message type: `std_msgs/String` containing JSON.

## Required Timing

When `vision_robot2` enters `SCANNING`, Robot2 is already at the C2S2 capture
pose. The piece should be mechanically stable, but the ML node must still wait
one second before taking the frame used for the dynamic pick.

```python
C2S2_DYNAMIC_PICK_SETTLE_SEC = float(
    os.environ.get("C2S2_DYNAMIC_PICK_SETTLE_SEC", "1.0")
)
```

Minimal callback shape:

```python
def _on_niryo_status(self, msg):
    try:
        status = json.loads(msg.data)
    except Exception:
        return

    if status.get("resource_id") != "vision_robot2":
        return
    if status.get("task") != "CAPTURE_LOCAL_VISION":
        return
    if status.get("resource_state") != "SCANNING":
        return

    command_id = status.get("command_id")
    if command_id and command_id == self._last_robot2_c2s2_command_id:
        return
    self._last_robot2_c2s2_command_id = command_id

    threading.Thread(
        target=self._compute_robot2_c2s2_pick_after_settle,
        args=(status,),
        daemon=True,
    ).start()
```

Worker shape:

```python
def _compute_robot2_c2s2_pick_after_settle(self, status):
    time.sleep(C2S2_DYNAMIC_PICK_SETTLE_SEC)

    # 1. Take the current cam4 frame.
    # 2. Run YOLO in the conveyor2 ROI.
    # 3. Use the centroid of the detected piece.
    # 4. Apply the C2S2 homography: pixel -> Robot2 XY mm.
    # 5. Call Robot2 IK for prepick_c2s2 and pick_c2s2.

    payload = {
        "prepick_c2s2": prepick_joints,
        "pick_c2s2": pick_joints,
        "x_mm": x_mm,
        "y_mm": y_mm,
        "command_id": status.get("command_id"),
        "piece_id": status.get("piece_id"),
        "trigger_resource_id": status.get("resource_id"),
        "triggered_at": time.time(),
        "settle_s": C2S2_DYNAMIC_PICK_SETTLE_SEC,
    }

    msg = String()
    msg.data = json.dumps(payload)
    self.robot2_pick_joints_pub.publish(msg)
```

## Supervisor Timeout

`shipyard_pnp` waits for this message after Robot2 local vision has finished.
If no valid message arrives within 3 seconds after that vision result, Robot2
uses the fixed C2S2 prepick/pick positions and logs a `fixed_timeout` row in:

```text
shipyard_pnp_ws.robot2_pick_joints_c2s2
```

