# Trainz 3D Model Formats: `.im`, `.trainzmesh`, and `.kin`

This document describes the structures recognized by TrainzLib's
reverse-engineered parser. It distinguishes observations supported by
the implementation from details that remain unverified.

```{=html}
<details>
```
```{=html}
<summary>
```
简体中文 / Chinese
```{=html}
</summary>
```
# Trainz 3D 模型格式：`.im`、`.trainzmesh` 和 `.kin`

本文介绍 TrainzLib 逆向解析器能够识别的 Trainz
模型格式结构。文中会区分代码中能够直接观察到的内容，以及仍未验证的格式细节。

## 简介

Trainz 使用多种二进制文件格式来保存 3D
资源及其动画数据。`.im`、`.trainzmesh` 和 `.kin`
是其中三种重要扩展名。它们可以共同用于构建带动画的资源，但用途不同，内部数据结构也不同。

TrainzLib
的解析代码提供了对这些格式的逆向分析，包括文件标识、几何数据、材质、骨骼层级和动画信息。部分字段仍被代码标记为"未验证"，因此不能将所有字段的具体含义都视为已经确定。

## 1. `.im` 格式

解析器通过 `JIRF` 文件标识以及位于偏移 `0x08` 的 `IDXM` 标识来识别 `.im`
文件。TrainzLib 将其视为包含几何、材质、骨骼信息和挂接点的模型格式。

### 内部结构

解析器识别出以下结构：

-   **IDXMINFO：** 包含模型信息，以及六个被解释为包围盒坐标的浮点数。
-   **CHNK：** 包含网格相关数据，包括材质和几何结构。
-   **MATL：** 保存材质名称、颜色相关数值、纹理引用和其他参数。
-   **GEOM：** 保存网格几何，包括顶点位置、UV 坐标、三角形索引和法线。
-   **SKEL：** 包含模型的骨骼层级。
-   **BONE：** 表示单个骨骼，包含名称、位置、四元数旋转和子节点数量。
-   **ATCH：** 包含挂接点信息，例如名称、旋转和位置。

解析器根据标签和长度字段遍历数据块，并根据骨骼记录的顺序和子节点数量重建层级。

部分结构是通过分析样本文件推断出来的。某些材质字段、包围盒偏移量和其他未公开数值的确切含义仍未验证。

### 几何与骨骼的关系

与常见的完全蒙皮角色网格不同，TrainzLib 所处理的 `.im`
几何按关联的骨骼组织为子网格。解析器读取骨骼局部坐标中的几何，并在内部处理中将其转换到模型空间。

这种组织方式适用于刚性附着到特定骨骼的部件，例如车轮、转向架和其他组件。

模型可以包含骨骼层级，但不包含动画关键帧。按照解析器的解释，`.im`
文件提供动画所需的结构，而单独的 `.kin` 文件提供运动数据。

没有骨骼的模型也可以被处理：TrainzLib
会在内部创建一个单位根节点，使几何能够使用统一的处理和导出流程。这只是实现层面的便利，并不代表原始文件一定包含根骨骼。

### 挂接点

`ATCH` 结构对 Trainz
资源尤其重要。它保存带名称的挂接点及其变换信息，例如 `a.bog0` 和
`a.smoke0`。

这些点可以描述其他组件或特效应附着在模型上的位置。TrainzLib
会将它们与骨骼分开读取，并可在导出 glTF 时将其保留为普通变换节点。

## 2. `.trainzmesh` 格式

TrainzLib 通过四字节标识 `tzMF` 识别 `.trainzmesh` 文件。

该格式包含文件头、骨骼记录和子网格数据。解析器读取多个文件头字段，包括版本、骨骼和子网格相关计数、三角形相关信息，以及六个浮点包围范围数值。

### 顶点布局

此格式的一个特点是使用布局描述来指定顶点数据。TrainzLib
会解析布局字符串，以确定每个顶点存储了哪些属性。

  属性标记   解析器中的含义
  ---------- ------------------------
  `P3f`      三维顶点位置
  `Wi4B`     四个骨骼索引或权重索引
  `Wg4f`     四个浮点骨骼权重
  `N3f`      三维法线
  `Tg3f`     三维切线相关属性
  `T02f`     一组二维纹理坐标
  `T12f`     另一组二维纹理坐标

部分命名约定的具体含义，是根据解析器如何使用数据推断出来的。上表描述的是代码中的解释，并非完整的官方格式规范。

解析器会将支持的布局转换为统一的内部表示，包括位置、骨骼索引、骨骼权重、法线和
UV 坐标。如果缺少某些属性，它可以根据三角形计算法线、提供默认 UV
坐标，或将顶点绑定到根骨骼。

### 子网格与材质

`.trainzmesh`
可以包含多个子网格。每个子网格包含顶点数据、三角形索引和材质信息。

材质读取器会提取着色器名称、材质名称、颜色值、纹理引用和其他参数。这些信息可用于重建网格并在导出时生成材质分配。

源代码也指出，部分文件头字段和不透明的子网格数据尚未完全识别。因此，该实现应被视为能够处理已识别结构的解析器，而不是覆盖所有
`.trainzmesh` 变体的最终规范。

### 骨骼权重

与 `.im` 读取器处理的刚性骨骼关联几何不同，`.trainzmesh`
顶点可以包含明确的骨骼索引和浮点权重。

这些数据描述顶点如何关联到骨骼，以便进行蒙皮模型处理。TrainzLib
在构建内部网格表示以及导出常规蒙皮模型时会使用这些值。

在保留层级的 glTF
导出模式下，实现还可以将蒙皮几何拆分为与骨骼关联的刚性部分。这是导出器采用的转换策略，并不意味着原始
`.trainzmesh` 本身就是以刚性部分保存的。

## 3. `.kin` 动画格式

`.kin` 格式保存动画信息。TrainzLib 将其识别为基于 `JIRF`
的格式，并解析其中的骨骼层级和帧数据。

动画通过带名称的骨骼及其随时间变化的一系列变换来表示。解析器处理位置和四元数数据，重建骨骼关系，并将动画转换为统一的内部表示。

动画数据包括：

-   骨骼名称和父级关系。
-   一系列动画帧。
-   每根骨骼的变换值。
-   用于播放和导出的帧率。

实现会处理位置和旋转数据，并在必要时从帧数据推导局部变换。随后，这些数据可用于模型摆姿、在查看器中播放动画，或在导出的
glTF 文件中生成动画轨道。

现有源代码并未证明所有 `.kin`
字段都有完整的官方规范，因此未公开字段的具体细节仍应视为暂定结论。

### 动画与模型匹配

`.kin` 文件不一定能用于任意模型。TrainzLib
会比较动画与模型的骨骼数量、骨骼名称和父级层级，以检查兼容性。

如果骨骼数量不同、名称不一致或层级结构不同，就可能无法匹配。

尤其对于 `.im`
文件，存在骨骼并不意味着模型内部包含动画关键帧。模型可能需要配套且兼容的外部
`.kin` 文件。

## 4. 三种格式如何配合使用

这三种扩展名在 Trainz 资源工作流程中承担互补的角色。

  格式            主要用途             重要信息
  --------------- -------------------- ----------------------------------
  `.im`           模型几何与结构       子网格、材质、骨骼、挂接点
  `.trainzmesh`   网格几何及相关数据   顶点布局、索引、材质、骨骼权重
  `.kin`          动画                 随帧变化的骨骼变换和动画时间信息

典型工作流程是读取模型文件、重建几何和层级，并可选加载兼容的动画。然后可以预览模型，或将其转换为其他格式。

模型结构与动画数据的分离尤其重要。模型可能拥有完整的骨骼层级，但在提供合适动画之前仍然是静态的。

## 5. 转换与结构保留

转换这些格式时，需要区分保留模型外观与保留模型内部结构。

常规蒙皮导出会通过蒙皮和关节层级来表示变形。保留层级的导出方式则将骨骼表示为普通变换节点。当目标是保留名称、父子关系和刚性附着部件，同时不创建蒙皮关节时，后一种方式很有用。

TrainzLib 的 glTF
导出也可以将带名称的挂接点保留为普通节点。不过，某些转换方式必然会重新组织几何，或近似处理源材质。尤其是针对带权重的
`.trainzmesh`
几何进行刚性部分转换时，这属于导出器的转换行为，并非对原始资源逐字节的保留。

## 6. 逆向分析的局限

现有实现为理解这些格式提供了有用基础，但它并不是完整的正式规范。

仍有一些细节尚不确定：

-   某些文件头和材质字段的确切含义。
-   部分顶点布局属性的完整语义。
-   某些数据块值和不透明字段的解释。
-   所有受支持或旧版本变体是否都采用相同结构。
-   不同文件是否都遵循相同的动画空间和变换约定。

解析器自身的注释明确将部分细节标记为未验证，并指出格式的部分结构是通过数量有限的样本资源逆向推断出来的。

因此，最可靠的结论是解析器直接读取并成功处理的结构。对于未公开字段或所有
Trainz 版本的更广泛结论，则需要更多样本、受控测试或权威格式文档来验证。

## 结论

`.im`、`.trainzmesh` 和 `.kin` 在 Trainz 的 3D
资源流程中承担不同但相关的职责。按照 TrainzLib 的解释，`.im`
将几何与命名骨骼和挂接点组织在一起；`.trainzmesh`
提供基于顶点布局的网格表示，并支持骨骼权重；`.kin`
则提供与骨骼层级关联的动画变换。

这三种格式共同提供了表示许多 Trainz
资源所需的几何、结构和运动信息。理解它们之间的区别，有助于检查模型、匹配动画文件，并在转换资源时尽可能保留原有组织结构。

```{=html}
</details>
```

------------------------------------------------------------------------

## Introduction

Trainz uses several binary file formats to represent 3D assets and their
animation data. Three important extensions are `.im`, `.trainzmesh`, and
`.kin`. Although they can be used together to construct an animated
asset, they serve different purposes and store information in different
ways.

The TrainzLib parser provides a reverse-engineered look at these
formats, identifying their headers, geometry structures, material data,
skeleton hierarchies, and animation information. The implementation
documents some fields as unverified, so the exact meaning of every byte
and field cannot be considered established.

## 1. The `.im` format

The `.im` format is identified by a `JIRF` file signature and an `IDXM`
identifier at byte offset `0x08` in the parser's implementation.
TrainzLib treats it as a model format containing geometry, materials,
bone information, and attachment points.

### Internal structure

The parser identifies several important structures:

-   **IDXMINFO:** Contains model information and a set of six
    floating-point values interpreted as bounding-box coordinates.
-   **CHNK:** Contains mesh-related data, including material and
    geometry structures.
-   **MATL:** Stores material names, color-related values, texture
    references, and additional parameters.
-   **GEOM:** Stores mesh geometry, including vertex positions, UV
    coordinates, triangle indices, and normals.
-   **SKEL:** Contains the model's skeleton hierarchy.
-   **BONE:** Represents an individual bone, including its name,
    position, quaternion rotation, and child count.
-   **ATCH:** Contains attachment-point information, including names,
    rotations, and positions.

The parser walks through chunks using their tags and length fields. It
reconstructs the hierarchy from the order of bone records and their
child counts.

Some of the structure has been inferred from examining sample files. In
particular, the precise meaning of certain material fields, bounding-box
offsets, and other undocumented values remains unverified.

### Geometry and bone relationships

Unlike a typical fully skinned character mesh, the `.im` geometry
handled by TrainzLib is organized into submeshes associated with
individual bones. The parser reads the geometry in bone-local
coordinates and transforms it into model space for internal processing.

This arrangement is important for rigidly attached parts, such as
wheels, bogeys, and other components that follow a particular bone.

A model can also contain a skeleton without containing animation
keyframes. In the parser's interpretation, the `.im` file provides the
structure that animation can operate on, while a separate `.kin` file
supplies the motion data.

Models without a skeleton are also handled: TrainzLib creates an
internal identity root node so that the geometry can pass through its
common processing and export routines. This is an implementation
convenience, not evidence that the original file necessarily contains a
root bone.

### Attachment points

The `ATCH` structure is especially relevant to Trainz assets. It stores
named attachment points with transformation information. Examples of
names include `a.bog0` and `a.smoke0`.

These points can describe where other components or effects are attached
to a model. TrainzLib reads them separately from the skeleton and can
preserve them as ordinary transform nodes during glTF export.

## 2. The `.trainzmesh` format

TrainzLib identifies `.trainzmesh` files through the four-byte `tzMF`
signature.

The format contains a header followed by bone records and submesh data.
The parser reads several header values, including a version field,
counts associated with bones and submeshes, triangle-related
information, and six floating-point bounding values.

### Vertex layouts

One of the distinctive features of this format is its layout description
for vertex data. TrainzLib interprets layout strings to determine which
attributes are stored for each vertex.

  Attribute token   Meaning in the parser
  ----------------- ----------------------------------------------
  `P3f`             Three-component vertex position
  `Wi4B`            Four bone indices or weights indices
  `Wg4f`            Four floating-point bone weights
  `N3f`             Three-component normal
  `Tg3f`            Three-component tangent-related attribute
  `T02f`            Two-component texture coordinate set
  `T12f`            Another two-component texture coordinate set

The exact meanings of some naming conventions are inferred from how the
parser uses the data. The table describes the implementation's
interpretation rather than a complete official format specification.

The parser converts supported layouts into a common internal
representation containing positions, bone indices, bone weights,
normals, and UV coordinates. If certain attributes are missing, it can
calculate normals from the triangles, provide default UV coordinates, or
bind vertices to the root bone.

### Submeshes and materials

A `.trainzmesh` can contain multiple submeshes. Each submesh includes
vertex data, triangle indices, and material information.

The material reader extracts shader and material names, color values,
texture references, and additional parameters. This information allows
TrainzLib to reconstruct the mesh and produce exports with material
assignments.

The source code also notes that some header fields and opaque submesh
values have not been fully identified. Therefore, the implementation
should be understood as a working parser for the structures it
recognizes, rather than a definitive description of every possible
`.trainzmesh` variant.

### Skeletal weighting

Unlike the rigid, bone-associated geometry handled by the `.im` reader,
`.trainzmesh` vertices can contain explicit bone indices and
floating-point weights.

These values describe how vertices are associated with bones for
skinned-model processing. TrainzLib uses them when producing its
internal mesh representation and when exporting a conventional skinned
model.

For its hierarchy-preserving glTF export, the implementation can also
split skinned geometry into rigid parts associated with bones. This is a
conversion strategy used by the exporter, not a claim that the original
`.trainzmesh` is stored as rigid parts.

## 3. The `.kin` animation format

The `.kin` format stores animation information. TrainzLib identifies it
as a `JIRF`-based format and parses its skeleton and frame data.

Animation is represented through a hierarchy of named bones and a
sequence of transforms over time. The parser processes position and
quaternion values, reconstructs bone relationships, and converts
animation data into a common internal representation.

The resulting animation data includes:

-   Bone names and parent relationships.
-   A sequence of animation frames.
-   Per-bone transformation values.
-   A frame rate used for playback and export.

The implementation handles position and rotation data and derives local
transforms from the frame data when necessary. Its internal animation
representation can then be used to pose a model, play an animation in
the viewer, or generate animation tracks in an exported glTF file.

The available source code does not establish a complete official
specification for every `.kin` field, so undocumented details should
remain provisional.

### Matching an animation to a model

A `.kin` file cannot necessarily be used with any arbitrary model.
TrainzLib checks compatibility by comparing the animation's bone count,
bone names, and parent hierarchy against the model.

A mismatch can occur if the animation contains a different number of
bones, uses different names, or has a different hierarchy.

For `.im` files in particular, the presence of bones does not by itself
indicate that animation keyframes are embedded in the model. A
compatible external `.kin` file may be needed.

## 4. How the three formats work together

The three extensions represent complementary parts of a Trainz asset
workflow.

  -----------------------------------------------------------------------
  Format                  Primary role            Important information
  ----------------------- ----------------------- -----------------------
  `.im`                   Model geometry and      Submeshes, materials,
                          structure               skeleton, attachment
                                                  points

  `.trainzmesh`           Mesh geometry and       Vertex layouts,
                          associated data         indices, materials,
                                                  bone weights

  `.kin`                  Animation               Bone transforms across
                                                  frames and animation
                                                  timing
  -----------------------------------------------------------------------

A typical workflow involves reading a model file, reconstructing its
geometry and hierarchy, and optionally loading a compatible animation.
The resulting model can then be previewed or converted into another
format.

The separation between model structure and animation data is
particularly significant. A model may have a complete hierarchy but
remain static until an appropriate animation is supplied.

## 5. Conversion and preservation

When converting these formats, it is important to distinguish between
preserving the appearance of a model and preserving its internal
structure.

A conventional skinned export represents deformation through a skin and
joint hierarchy. A hierarchy-preserving export instead represents bones
as ordinary transform nodes. The latter approach is useful when the
objective is to retain names, parent-child relationships, and rigidly
attached parts without creating skeletal joints.

TrainzLib's glTF export can also preserve named attachment points as
ordinary nodes. However, some conversion methods necessarily reorganize
geometry or approximate source material behavior. In particular, the
source code's rigid-part conversion for weighted `.trainzmesh` geometry
is an exporter-specific transformation, not a byte-for-byte preservation
of the original asset.

## 6. Reverse-engineering limitations

The available implementation provides a useful foundation for
understanding the formats, but it is not a complete formal
specification.

Several details remain uncertain:

-   The exact meaning of certain header and material fields.
-   The full semantics of some vertex-layout attributes.
-   The interpretation of some chunk values and opaque fields.
-   Whether every supported or legacy variant follows the same
    structures.
-   Whether every animation-space and transformation convention applies
    to all files.

The parser's own comments identify some of these details as unverified
and note that parts of the format were reverse-engineered from a limited
set of sample assets.

Consequently, the most reliable statements are those directly
demonstrated by the structures the parser reads and successfully
processes. Broader conclusions about undocumented fields or all Trainz
versions would require additional samples, controlled testing, or
authoritative format documentation.

## Conclusion

The `.im`, `.trainzmesh`, and `.kin` formats serve distinct but related
roles in Trainz's 3D asset pipeline. The `.im` format, as interpreted by
TrainzLib, organizes geometry around named bones and attachment points;
`.trainzmesh` provides a vertex-layout-based mesh representation with
support for skeletal weights; and `.kin` supplies animation transforms
associated with a bone hierarchy.

Together, these formats provide the geometry, structure, and motion
needed to represent many Trainz assets. Understanding their differences
is essential for inspecting models, matching animation files, and
converting assets while retaining as much of their original organization
as possible.
