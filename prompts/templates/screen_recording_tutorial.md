## Template: Screen Recording / Tutorial Walkthrough
Built from the owner's screen recording (in the footage list). Desired outcome → steps → result →
short recap. Shot 1 (`role` "outcome") shows the finished result first. Each "step" is a clip of
that step in the recording, with `label` "Step 1", "Step 2" … and `text` a callout of what to
click or type (at most 7 words). Set `focus` to the box around the part of the screen that
matters (fractions of the frame: x, y from the top left, w, h) so the UI is readable on a phone.
A slow stretch (a long install, a render) may play sped up: set `timelapse` true and pick the
whole window. Never show passwords, keys or personal data.
