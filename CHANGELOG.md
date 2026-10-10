# Changelog

## 0.3.1 — joint and artwork assembly fixes

- Replace the README robot illustration with the author-approved original character, wave and thinking animations, shown together at the top.
- Register replacement hands from measured wrist edges, matching pivot, width and orientation instead of guessing image-center offsets.
- Calibrate attachment RGB from opaque source/reference skin samples without editing original PNGs; feather overlapping wrist roots in the renderer.
- Bind continuous skin across bare elbows with joint strips, preserving original motion curves and avoiding independent elbow cut edges.
- Apply persistent named layer constraints after animated draw order, so a thinking hand remains in front of the face. Fidelity locks and recipe fingerprints include these constraints.
- Reject part extraction that removes explicitly required opaque garment/skin areas. Missing hidden artwork still requires suitable source art.
- Reject explicitly forbidden pixels owned by adjacent parts, including connected sleeve remnants that component checks cannot detect.
- Preserve silhouette hull corners when generating joint strips, preventing slanted cuff/skin boundaries from being clipped between sampling rows. Existing meshes require rebinding from their original region cutouts.
- Document sewn armhole weighting: pin the inner seam to the chest and blend toward the arm at the outer sleeve/cuff.
- Add regression tests for joint registration, skin color, alpha, connected bent limbs, face/hand occlusion, texture isolation and garment coverage.
- These checks do not guarantee anatomy or visual quality for arbitrary unprepared images. Rendered drafts still require visual review.

## 0.3.0 — reproducible wave and thinking recipes

- Freeze the final V3.9 wave and V3.6 thinking tracks with 31 original test-character parts, six palm-turn poses and two curled-finger variants.
- Add five MCP recipe tools and a discoverable resource with wrist registration, cuff layering, weight, timing, reference and character-adaptation instructions.
- Validate rig and artwork hashes before restoring motions; preserve revisions and refuse mismatched characters or stale edits.
- Include an offline MCP replay example and package resources in both wheel and source distributions.
- Avoid an extra held frame when a four-decimal native endpoint lies on the frame grid.
- Reproduction checks remain separate from per-frame visual approval.

## 0.2.0 — standalone developer preview

- Separate MotionForge package and CLI, with no SpineMotion import or desktop editor integration.
- MCP character authoring, weighted meshes, rigid skinning, reference metadata, identity locks and CPU rendering.
- Review-aware exports: transparent WebP/APNG/PNG, binary-transparent GIF and spritesheets.
- Procedurally drawn MIT robot, executable MCP example, installation guide and motion-reference request template.
- Runtime dependency inventory, retained dependency license texts and reproducible source/user packaging.

This preview does not add a graphical interface, video motion capture, image generation or certification for game runtimes.
