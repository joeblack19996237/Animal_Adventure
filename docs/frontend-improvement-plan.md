# Phaser + TypeScript 前端渲染全面提升方案（修订版）

> **说明**：本文档基于原方案审核结果，修正了 6 个错误、补全了 6 个缺口，形成可直接执行的综合解决方案。  
> **Phaser 版本要求**：>= 3.60（PostFXPipeline、新粒子 API 均依赖此版本）

---

## 零、基础配置修复（最先做，P0）

这是成本最低、收益最高的修复，直接消除截图中的瓦片接缝问题。

```typescript
// main.ts — 在 new Phaser.Game({}) 中加入
const gameConfig: Phaser.Types.Core.GameConfig = {
  type: Phaser.AUTO,
  pixelArt: true,      // 关闭抗锯齿，使用最近邻采样 → 消除瓦片接缝
  roundPixels: true,   // 渲染坐标取整 → 防止角色抖动
  antialias: false,
  // ... 其余配置不变
};
```

---

## 一、Y-Sort 深度排序 — 消除割裂感的核心

### 1.1 深度层级分区常量

不是所有对象都参与 Y-Sort，先划定固定区间：

```typescript
// src/depth.ts
export const DEPTH = {
  GROUND:      0,       // 地面、河流底纹
  GROUND_DECO: 100,     // 地面装饰（花草、石头）
  SHADOW:      150,     // 所有脚部阴影（独立层，低于 Y-Sort 区间）

  // Y-Sort 动态区间：200–9800（世界 y 坐标范围 0~4800，乘以 2 映射至此）
  YSORT_MIN:   200,
  YSORT_MAX:   9800,

  OVERHEAD:    9900,    // 屋顶、树冠（始终在角色之上）
  HUD:         10000,   // UI 层（独立 Scene，无需干预）
} as const;
```

### 1.2 depth 计算的基准：用脚部而非中心

```typescript
// 所有可排序对象统一设置脚部原点
sprite.setOrigin(0.5, 1);  // 推荐！this.y 直接等于脚底世界坐标

// depth 公式：脚部 y 映射到 Y-Sort 区间
const depth = DEPTH.YSORT_MIN + sprite.y * 2;
sprite.setDepth(depth);
```

### 1.3 DepthSortPlugin — 统一管理排序对象

```typescript
// src/plugins/DepthSortPlugin.ts

export interface Sortable {
  gameObject: Phaser.GameObjects.GameObject & { y: number; setDepth(v: number): void };
  depthOffset?: number;   // 微调：同 y 时用 x 做次级排序或手动偏移
  isOverhead?: boolean;   // 屋顶、树冠等始终置顶
}

export class DepthSortPlugin {
  private sortables: Sortable[] = [];

  add(item: Sortable): void {
    this.sortables.push(item);
  }

  remove(go: Phaser.GameObjects.GameObject): void {
    this.sortables = this.sortables.filter(s => s.gameObject !== go);
  }

  update(): void {
    for (const item of this.sortables) {
      if (item.isOverhead) {
        item.gameObject.setDepth(DEPTH.OVERHEAD);
        continue;
      }
      // 同 y 的对象加微小偏移防止 z-fighting 闪烁
      const base = DEPTH.YSORT_MIN + item.gameObject.y * 2;
      item.gameObject.setDepth(Math.round(base) + (item.depthOffset ?? 0));
    }
  }
}
```

### 1.4 建筑的正确实现（修正 E1：不能用 Container）

**错误根因**：原方案用 `Phaser.GameObjects.Container`，Container 子对象的 `setDepth()` 只影响容器内部排序，**对全局场景深度无效**。必须使用独立 Sprite。

```typescript
// src/buildings/Building.ts
import { DEPTH } from '../depth';

export class Building {
  readonly bodySprite: Phaser.GameObjects.Sprite;  // 墙体，参与 Y-Sort
  readonly roofSprite: Phaser.GameObjects.Sprite;  // 屋顶，固定 OVERHEAD

  constructor(scene: Phaser.Scene, x: number, y: number, texture: string) {
    // 两个 Sprite 直接加入场景显示列表（非 Container 子对象）
    this.bodySprite = scene.add
      .sprite(x, y, texture, 'body')
      .setOrigin(0.5, 1);

    this.roofSprite = scene.add
      .sprite(x, y - this.bodySprite.displayHeight * 0.6, texture, 'roof')
      .setOrigin(0.5, 1)
      .setDepth(DEPTH.OVERHEAD);   // 屋顶固定置顶，不参与 Y-Sort
  }

  get sortableBody(): Phaser.GameObjects.Sprite { return this.bodySprite; }
  get sortableRoof(): Phaser.GameObjects.Sprite { return this.roofSprite; }

  destroy(): void {
    this.bodySprite.destroy();
    this.roofSprite.destroy();
  }
}
```

**若美术资源暂无 body/roof 拆分**（个人开发常见情况），用临时方案：

```typescript
// 单张建筑 Sprite，调低基线让角色更容易站到"前面"
building.setOrigin(0.5, 1);
// update() 中：基线向上偏移 15%（让墙体碰撞更合理）
building.setDepth(DEPTH.YSORT_MIN + (building.y - building.displayHeight * 0.15) * 2);
```

### 1.5 Overhead 图层的正确处理（修正 E4）

**错误根因**：原方案用 `forEachTile` 将整个 TilemapLayer 设为 depth 9999（影响整层，逻辑错误）。正确做法是在 Tiled 中建专用 Overhead 图层：

```typescript
// 在 Tiled 编辑器中：
// - 建一个名为 "Overhead" 的 Tile Layer，只放屋顶/树冠 tile
// - 建一个名为 "Ground" 的 Tile Layer，放地面 tile
// - 建一个名为 "Collision" 的 Tile Layer（tile 属性：collides: true）

// GameScene.ts — create()
const groundLayer    = map.createLayer('Ground', tileset)!.setDepth(DEPTH.GROUND);
const collisionLayer = map.createLayer('Collision', tileset)!.setAlpha(0); // 不可见，纯逻辑
const overheadLayer  = map.createLayer('Overhead', tileset)!.setDepth(DEPTH.OVERHEAD);
// 无需 forEachTile，整层固定即可
```

### 1.6 在 GameScene 中集成 DepthSortPlugin

```typescript
// GameScene.ts
export class GameScene extends Phaser.Scene {
  private depthSort!: DepthSortPlugin;

  create(): void {
    this.depthSort = new DepthSortPlugin();

    // 注册玩家
    this.depthSort.add({ gameObject: this.playerSprite });

    // 注册建筑（屋身参与 Y-Sort，屋顶固定 OVERHEAD）
    buildings.forEach(b => {
      this.depthSort.add({ gameObject: b.bodySprite });
      this.depthSort.add({ gameObject: b.roofSprite, isOverhead: true });
    });

    // 注册 NPC
    npcs.forEach(npc => this.depthSort.add({ gameObject: npc.sprite }));
  }

  update(): void {
    this.depthSort.update();  // 每帧一次，O(n)
  }
}
```

---

## 二、碰撞系统 — 全 ArcadePhysics 方案（修正 E2）

**修正原则**：移除 MatterJS，全部使用 ArcadePhysics。两套物理引擎不能互相产生碰撞——原方案 MatterJS 河流对 Arcade 角色无效。

### 2.1 Tiled 地图碰撞配置

在 Tiled 里设置 tile 自定义属性：
```
collides  : boolean = true   ← 普通障碍（墙、建筑基础）
isWater   : boolean = true   ← 水面（触发特效、降速，不完全阻挡）
```

建两个独立图层：`Ground`（纯视觉）、`Collision`（带 collides 属性）

### 2.2 激活 Tilemap 碰撞

```typescript
// GameScene.ts — create()
const map     = this.make.tilemap({ key: 'world' });
const tileset = map.addTilesetImage('tileset', 'tileset-img')!;

const collisionLayer = map.createLayer('Collision', tileset)!;
collisionLayer.setCollisionByProperty({ collides: true });
collisionLayer.setAlpha(0);   // 生产环境隐藏

// Debug 期间可视化（开发完删掉）
if (import.meta.env.DEV) {
  const dbg = this.add.graphics().setAlpha(0.5);
  collisionLayer.renderDebug(dbg, {
    tileColor: null,
    collidingTileColor: new Phaser.Display.Color(243, 134, 48, 200),
  });
}

this.physics.world.setBounds(0, 0, map.widthInPixels, map.heightInPixels);
this.cameras.main.setBounds(0, 0, map.widthInPixels, map.heightInPixels);
this.physics.add.collider(this.player, collisionLayer);
```

### 2.3 角色碰撞体 — 脚部碰撞体

```typescript
// Player.ts — configureBody()
private configureBody(): void {
  const body = this.body as Phaser.Physics.Arcade.Body;
  const spriteW = 32;
  const spriteH = 48;

  // 碰撞体只覆盖下方 30%，宽度 60%
  const bodyW = spriteW * 0.6;
  const bodyH = spriteH * 0.3;

  body.setSize(bodyW, bodyH);
  body.setOffset(
    (spriteW - bodyW) / 2,   // 水平居中
    spriteH - bodyH           // 贴近底部
  );
  body.setCollideWorldBounds(true);
}

/*
  精灵坐标系（setOrigin(0.5, 1)）：
  ┌────────────────────┐ ← y = -spriteH（顶部）
  │     精灵图像        │
  │   ┌────────────┐   │ ← offset.y = spriteH - bodyH
  │   │ 碰撞体 19×14│   │
  └───┴────────────┴───┘ ← y = 0（脚底，origin 点）
*/
```

### 2.4 建筑物碰撞体 — 只覆盖底部

```typescript
// BuildingManager.ts
export class BuildingManager {
  private staticGroup: Phaser.Physics.Arcade.StaticGroup;

  constructor(scene: Phaser.Scene, map: Phaser.Tilemaps.Tilemap) {
    this.staticGroup = scene.physics.add.staticGroup();

    const objects = map.getObjectLayer('Buildings')?.objects ?? [];
    objects.forEach(obj => {
      const building = this.staticGroup.create(
        obj.x! + obj.width! / 2,
        obj.y!,
        'buildings',
        obj.properties?.frame ?? 0
      ) as Phaser.Physics.Arcade.Sprite;

      building.setOrigin(0.5, 1);

      const bw = obj.width!;
      const bh = obj.height!;
      const bodyH = bh * 0.25;   // 只覆盖底部 25%（门槛位置）

      (building.body as Phaser.Physics.Arcade.StaticBody)
        .setSize(bw * 0.85, bodyH)
        .setOffset((bw - bw * 0.85) / 2, bh - bodyH);

      building.refreshBody();  // StaticBody 修改后必须 refresh
    });
  }

  addCollider(scene: Phaser.Scene, player: Phaser.Physics.Arcade.Sprite): void {
    scene.physics.add.collider(player, this.staticGroup);
  }
}
```

### 2.5 水面碰撞 — 纯 Arcade 方案（修正 E2：替换 MatterJS）

```typescript
// 在 Tiled 建 RiverCollision Object Layer，放矩形近似河岸区域
// （不需要 MatterJS 精确多边形）
const riverObjects = map.getObjectLayer('RiverCollision')?.objects ?? [];
const riverGroup   = this.physics.add.staticGroup();

riverObjects.forEach(obj => {
  // 不需要纹理的隐形 StaticBody
  const zone = this.add.zone(
    obj.x! + obj.width! / 2,
    obj.y! + obj.height! / 2,
    obj.width!,
    obj.height!
  );
  this.physics.add.existing(zone, true);
  riverGroup.add(zone);
});

// overlap（不阻挡，触发特效 + 降速）
this.physics.add.overlap(
  this.player,
  riverGroup,
  () => { this.onEnterWater(); },
  undefined,
  this
);

// 若需要完全阻挡（不允许入水），改为：
// this.physics.add.collider(this.player, riverGroup);
```

水面特效触发：

```typescript
private onEnterWater(): void {
  if (this.playerData.getData('inWater')) return;
  this.playerData.setData('inWater', true);
  this.rippleEffect.play(this.player.x, this.player.y);
  (this.player.body as Phaser.Physics.Arcade.Body).setMaxVelocity(80, 80);
}
```

### 2.6 碰撞调试器（开发期必备）

```typescript
// utils/CollisionDebugger.ts
export class CollisionDebugger {
  private graphics: Phaser.GameObjects.Graphics;
  private enabled = true;

  constructor(scene: Phaser.Scene) {
    this.graphics = scene.add.graphics().setDepth(99999);
    scene.input.keyboard!.on('keydown-D', () => {
      this.enabled = !this.enabled;
      this.graphics.clear();
    });
  }

  update(bodies: Phaser.Physics.Arcade.Body[]): void {
    if (!this.enabled) return;
    this.graphics.clear();
    bodies.forEach(body => {
      this.graphics
        .lineStyle(1, 0x00ff00, 0.8)
        .strokeRect(body.x, body.y, body.width, body.height);
    });
  }
}
```

---

## 三、相机与比例

### 3.1 初始化相机（修正 G6：补充瞬间定位）

```typescript
// GameScene.ts — create()
create(): void {
  const cam = this.cameras.main;

  cam.setBounds(0, 0, map.widthInPixels, map.heightInPixels);
  cam.setZoom(2.0);   // 卡通俯视探索游戏推荐 1.5–2.5

  // 先瞬间跳到玩家位置，再开始平滑跟随
  // 若不加这行，开场相机会从 (0,0) 慢速漂移 1~2 秒
  cam.centerOn(this.player.x, this.player.y);
  cam.startFollow(this.player, true, 0.1, 0.1);
  // roundPixels 已在 gameConfig 中全局设置，无需单独设
}
```

### 3.2 角色比例修正（修正 G2：zoom 不解决相对比例）

Camera zoom 同等放大地图和角色，不改变两者的相对大小。若角色精灵本身太小，需独立缩放：

```typescript
// 角色 setScale 独立调整，不受 camera zoom 影响
this.player.setScale(1.5);  // 根据实际精灵尺寸调整
// 缩放后碰撞体需重新配置（setScale 不影响物理体大小）
```

### 3.3 CameraController — 封装高级行为

```typescript
// camera/CameraController.ts
export interface CameraConfig {
  zoom:       number;
  lerpX:      number;
  lerpY:      number;
  leadOffset: number;   // 向移动方向预瞄的像素数
  deadzoneW:  number;
  deadzoneH:  number;
}

export class CameraController {
  private cam: Phaser.Cameras.Scene2D.Camera;
  private lastDir = 1;
  private currentOffsetX = 0;

  constructor(
    scene: Phaser.Scene,
    private target: Phaser.GameObjects.Sprite,
    private config: CameraConfig
  ) {
    this.cam = scene.cameras.main;
    this.cam.setZoom(config.zoom);
    this.cam.centerOn(target.x, target.y);    // 瞬间定位
    this.cam.startFollow(target, true, config.lerpX, config.lerpY);
    this.cam.setDeadzone(config.deadzoneW, config.deadzoneH);
  }

  update(): void {
    const body = this.target.body as Phaser.Physics.Arcade.Body;

    if (body.velocity.x > 10)       this.lastDir =  1;
    else if (body.velocity.x < -10) this.lastDir = -1;

    const targetOffsetX = this.lastDir * this.config.leadOffset;
    this.currentOffsetX = Phaser.Math.Linear(this.currentOffsetX, targetOffsetX, 0.05);
    this.cam.setFollowOffset(-this.currentOffsetX, 0);
  }

  shake(intensity = 0.005, duration = 250): void {
    this.cam.shake(duration, intensity);
  }

  zoomTo(targetZoom: number, duration = 400): void {
    this.cam.zoomTo(targetZoom, duration, 'Sine.easeInOut');
  }
}
```

### 3.4 视差层 — 俯视游戏适配版（修正 G3：移除不适用的天空/远山层）

原方案的天空/远山/云层视差是**横版卷轴**设计，对俯视探索游戏不适用。俯视游戏的视差只在地面装饰层做轻微差速：

```typescript
// GameScene.ts — setupParallaxLayers()
// ✅ 俯视游戏正确视差结构
setupParallaxLayers(map: Phaser.Tilemaps.Tilemap, tileset: Phaser.Tilemaps.Tileset): void {

  // 主地面层：正常速度（默认 scrollFactor=1.0）
  this.groundLayer = map.createLayer('Ground', tileset)!
    .setDepth(DEPTH.GROUND);

  // 地面装饰层（花草、石头）：稍微慢一点，制造轻微纵深感
  this.groundDecoLayer = map.createLayer('GroundDeco', tileset)!
    .setScrollFactor(0.92)
    .setDepth(DEPTH.GROUND_DECO);

  // Overhead 层：固定，随地图正常滚动
  this.overheadLayer = map.createLayer('Overhead', tileset)!
    .setDepth(DEPTH.OVERHEAD);
}

// update() 中不需要手动更新 tilePositionX（setScrollFactor 自动处理）
// ❌ 以下写法仅用于自动平铺的 tileSprite，不用于 Tilemap 层
// this.farBgLayer.tilePositionX = camX * 0.05;  ← 不适用
```

---

## 四、角色接地感 — 阴影与融合（统一版，修正 E5/E6）

### 4.1 脚部椭圆阴影（统一使用 setOrigin(0.5, 1)）

原方案两处阴影代码互相矛盾，以下为统一版本：

```typescript
// Player.ts — 假设 setOrigin(0.5, 1) 已设置
export class Player extends Phaser.Physics.Arcade.Sprite {
  private shadow!: Phaser.GameObjects.Ellipse;

  create(): void {
    this.setOrigin(0.5, 1);   // 原点在脚底，this.y = 脚底世界坐标

    // 阴影初始化：位置基于脚底（this.y），不加 displayHeight 偏移
    this.shadow = this.scene.add.ellipse(
      this.x,
      this.y - 2,          // 略高于脚底，视觉上贴地
      this.displayWidth * 0.6,
      8,
      0x000000, 0.2
    );
    // 阴影 depth 固定在 SHADOW 层（150），低于 YSORT_MIN（200），永远在角色脚下
    this.shadow.setDepth(DEPTH.SHADOW);
  }

  update(): void {
    // 阴影跟随角色脚部位置
    this.shadow.x = this.x;
    this.shadow.y = this.y - 2;

    // 移动时横向拉伸阴影，模拟速度感
    const speed = (this.body as Phaser.Physics.Arcade.Body).speed;
    const stretch = 1 + Math.min(speed / 300, 0.5);
    this.shadow.setScale(stretch, 1);

    // 角色 depth 由 DepthSortPlugin 统一管理，此处不重复设置
  }
}
```

> **为什么阴影用固定 SHADOW depth（150）而非 playerDepth - 1？**  
> 原方案用 `playerDepth - 1` 会随角色 y 值变化而改变，导致阴影可能高于某些地面装饰（depth=100）。固定 150 更简单且不会出错。

### 4.2 建筑遮挡半透明

```typescript
// 当角色走入建筑"阴影区"时，建筑墙体半透明
this.physics.overlap(this.player, this.buildingZones, (_, zone) => {
  const building = zone.getData('building') as Building;
  this.tweens.add({
    targets: building.bodySprite,   // 注意：修正为 bodySprite，不是 Container
    alpha: 0.55,
    duration: 150,
    ease: 'Linear',
  });
});
```

---

## 五、角色动画系统（补全 G5 — 原方案完全缺失）

方向动画是探索游戏沉浸感的基础，原方案未提及：

```typescript
// 在 GameScene.create() 或 Player 构造中注册
registerAnimations(scene: Phaser.Scene, textureKey: string): void {
  const dirs = ['down', 'up', 'left', 'right'] as const;

  dirs.forEach(dir => {
    // idle（站立）
    scene.anims.create({
      key: `idle_${dir}`,
      frames: scene.anims.generateFrameNames(textureKey, {
        prefix: `idle_${dir}_`, start: 0, end: 0,
      }),
      frameRate: 1,
      repeat: -1,
    });

    // walk（行走循环）
    scene.anims.create({
      key: `walk_${dir}`,
      frames: scene.anims.generateFrameNames(textureKey, {
        prefix: `walk_${dir}_`, start: 0, end: 3,
      }),
      frameRate: 8,
      repeat: -1,
    });
  });
}

// update() 中根据速度方向切换动画
updateAnimation(vx: number, vy: number): void {
  const moving = Math.abs(vx) > 10 || Math.abs(vy) > 10;
  const dir = this.getFacingDir(vx, vy);  // 'up'|'down'|'left'|'right'

  const key = moving ? `walk_${dir}` : `idle_${dir}`;
  if (this.anims.currentAnim?.key !== key) {
    this.play(key, true);
  }
}

private getFacingDir(vx: number, vy: number): 'up' | 'down' | 'left' | 'right' {
  if (Math.abs(vy) > Math.abs(vx)) return vy < 0 ? 'up' : 'down';
  return vx < 0 ? 'left' : 'right';
}
```

---

## 六、后处理与光照 — 色温统一（修正 E3：PostFXPipeline 注册方式）

### 6.1 正确的注册方式（Phaser 3.60+）

```typescript
// WarmTonePipeline.ts
export class WarmTonePipeline extends Phaser.Renderer.WebGL.Pipelines.PostFXPipeline {
  constructor(game: Phaser.Game) {
    super({
      game,
      name: 'WarmTone',
      fragShader: `
        precision mediump float;
        uniform sampler2D uMainSampler;
        varying vec2 outTexCoord;
        void main() {
          vec4 color = texture2D(uMainSampler, outTexCoord);
          color.r *= 1.04;
          color.g *= 1.01;
          color.b *= 0.96;
          gl_FragColor = color;
        }
      `,
    });
  }
}

// GameScene.create() 中注册（不是在 Phaser.Game config 里！）
create(): void {
  // 正确：通过 renderer 注册 PostFXPipeline
  (this.renderer as Phaser.Renderer.WebGL.WebGLRenderer)
    .pipelines.addPostPipeline('WarmTone', WarmTonePipeline);

  // 然后应用到角色和 NPC
  this.player.setPostPipeline('WarmTone');
  npcs.forEach(npc => npc.sprite.setPostPipeline('WarmTone'));
}
```

> **个人开发建议**：PostFX Shader 有学习成本且 WebGL 兼容性需要额外测试。可暂时用 `sprite.setTint(0xFFF0E0)` 代替暖色调（一行代码，效果近似，无兼容问题）。

---

## 七、水面涟漪特效（Arcade 版，修正 E2）

```typescript
// effects/RippleEffect.ts
export class RippleEffect {
  private emitter: Phaser.GameObjects.Particles.ParticleEmitter;

  constructor(scene: Phaser.Scene) {
    const gfx = scene.add.graphics();
    gfx.fillStyle(0xffffff, 0.6);
    gfx.fillCircle(8, 8, 8);
    gfx.generateTexture('ripple-particle', 16, 16);
    gfx.destroy();

    this.emitter = scene.add.particles(0, 0, 'ripple-particle', {
      speed:    { min: 20, max: 50 },
      angle:    { min: 0, max: 360 },
      scale:    { start: 0.4, end: 0 },
      alpha:    { start: 0.6, end: 0 },
      lifespan: 400,
      tint:     0x4a9fd4,
      emitting: false,
    });
    this.emitter.setDepth(DEPTH.YSORT_MIN - 1);
  }

  play(x: number, y: number): void {
    this.emitter.setPosition(x, y);
    this.emitter.explode(6);
  }
}
```

---

## 八、优先级路线图

| 优先级 | 改动 | 成本 | 预期效果 |
|--------|------|------|----------|
| **P0（立刻做）** | `pixelArt: true` + `roundPixels: true` | 2 行代码 | 消除瓦片接缝、角色抖动 |
| **P0（立刻做）** | Tilemap 碰撞层 + 建筑碰撞体 | 1 天 | 消除穿模，建立物理边界 |
| **P0（立刻做）** | Y-Sort 深度排序（独立 Sprite 方案） | 半天 | 建筑与角色正确遮挡 |
| **P1（本周）** | 脚部阴影 + 相机 zoom + centerOn() | 半天 | 接地感、消除开场漂移 |
| **P1（本周）** | 角色 setScale() + 动画系统 | 1 天 | 比例感、方向动画 |
| **P2（迭代）** | 地面装饰层视差（scrollFactor=0.9） | 2 小时 | 轻微纵深感 |
| **P2（迭代）** | 建筑遮挡半透明 | 2 小时 | 探索代入感 |
| **P3（打磨）** | PostFX 色温（或 setTint 简化版） | 半天 | 美术统一性 |

---

## 九、工作量评估与个人开发者调整

### 工作量（全新开始）

| 类别 | 专业团队 | 含 AI 工具的个人开发 |
|------|---------|-----------------|
| **美术**：角色精灵表（4方向×动画帧） | 30–60 h | 40–80 h（一致性难保证） |
| **美术**：建筑 body+roof 拆分 | 20–40 h | 30–60 h（需要手动切图） |
| **美术**：Tileset（地面/碰撞/装饰/树冠） | 40–80 h | 50–100 h |
| **代码**：Y-Sort + 碰撞 + 相机 | 10–20 h | 4–8 h（Claude Code 辅助） |
| **代码**：动画 + 阴影 + 视差 | 8–16 h | 3–6 h（Claude Code 辅助） |
| **代码**：调试与调参 | 6–10 h | 3–5 h |
| **合计** | **~114–226 h** | **~130–259 h**（美术是瓶颈） |

### 个人开发者（Claude Code + 现有素材）建议调整

| 原方案项目 | 调整 | 原因 |
|-----------|------|------|
| Building body/roof 精准拆分 | **简化为单张 Sprite + 低 baseline 偏移** | 无专业美工时切图工作量大且效果有限 |
| MatterJS 河流碰撞 | **删除，改用 Arcade 矩形近似** | 两套物理引擎维护成本高，矩形对探索游戏足够 |
| PostFX Shader 色温 | **先用 setTint() 代替** | 一行代码、零兼容风险，后期再升级 |
| 天空/远山/云层视差 | **删除** | 俯视游戏不适用 |
| DepthSortPlugin 封装 | **可选**，初期直接在 update() 调 setDepth | 小项目可不封装 |

**简化后个人开发实际工作量（使用现有截图中的美术素材）**：

| 阶段 | 工作量 |
|------|--------|
| Tiled 地图配置（碰撞层、Overhead 层） | 3–6 h |
| P0 代码（pixelArt fix + Y-Sort + 碰撞） | 4–8 h |
| P1 代码（相机 + 阴影 + 动画） | 3–6 h |
| P2+ 代码（视差 + 遮挡 + PostFX） | 3–5 h |
| 调试与视觉调参 | 3–5 h |
| **合计** | **~16–30 h** |
