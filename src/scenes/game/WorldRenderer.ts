import Phaser from 'phaser';
import assetsJson from '../../../config/assets.json';
import charactersJson from '../../../config/characters.json';
import npcsJson from '../../../config/npcs.json';
import type { WorldItemRecord } from './gameRecords';

type AssetManifest = Record<string, string>;

interface CharacterConfig {
  id: string;
  scale: number;
  anchor: { x: number; y: number };
  states: {
    stand: Record<string, string | boolean>;
    walk: Record<string, string | string[] | boolean>;
  };
}

interface NpcConfig {
  id: string;
  name: string;
  asset_id: string;
  x: number;
  y: number;
}

const ASSETS = assetsJson as AssetManifest;
const CHARACTERS = charactersJson as CharacterConfig[];
const NPCS = npcsJson as NpcConfig[];
const DEFAULT_CHARACTER_ID = 'penguin';
const WALK_FRAME_MS = 110;

export function loadWorldTextures(scene: Phaser.Scene): void {
  for (const [key, url] of Object.entries(ASSETS)) {
    if (!url.endsWith('.png')) continue;
    if (key === 'map_full') continue;
    if (scene.textures.exists(key)) continue;
    scene.load.image(key, url);
  }
}

export class WorldRenderer {
  private playerSprite: Phaser.GameObjects.Image | null = null;
  private playerCharacterId = DEFAULT_CHARACTER_ID;
  private readonly npcSprites: Phaser.GameObjects.Image[] = [];
  private readonly worldItemSprites = new Map<string, Phaser.GameObjects.Image>();
  private hasCenteredCamera = false;

  constructor(private readonly scene: Phaser.Scene) {}

  createNpcs(onNpcInteract: (npcId: string) => void): void {
    for (const npc of NPCS) {
      if (!this.scene.textures.exists(npc.asset_id)) continue;
      const sprite = this.scene.add
        .image(npc.x, npc.y, npc.asset_id)
        .setDepth(npc.y)
        .setScale(0.45)
        .setInteractive({ useHandCursor: true });
      sprite.on('pointerdown', () => onNpcInteract(npc.id));
      this.npcSprites.push(sprite);
    }
  }

  updatePlayerFromServer(player: Record<string, unknown>): void {
    const characterId =
      typeof player['character_id'] === 'string' ? player['character_id'] : DEFAULT_CHARACTER_ID;
    const x = typeof player['x'] === 'number' ? player['x'] : 0;
    const y = typeof player['y'] === 'number' ? player['y'] : 0;
    const direction = typeof player['direction'] === 'string' ? player['direction'] : 'front';

    this.playerCharacterId = characterId;
    this.ensurePlayerSprite();
    this.updatePlayerPosition(x, y, direction, false);
    if (!this.hasCenteredCamera) {
      this.scene.cameras.main.centerOn(x, y);
      this.hasCenteredCamera = true;
    }
  }

  updatePlayerPosition(x: number, y: number, direction: string, isMoving = false): void {
    this.ensurePlayerSprite();
    if (this.playerSprite === null) return;
    const { key, flipX } = this.resolveCharacterTexture(
      this.playerCharacterId,
      direction,
      isMoving,
      this.scene.time.now,
    );
    if (this.scene.textures.exists(key) && this.playerSprite.texture.key !== key) {
      this.playerSprite.setTexture(key);
    }
    this.playerSprite.setFlipX(flipX);
    this.playerSprite.setPosition(x, y);
    this.playerSprite.setDepth(y + 10);
  }

  renderWorldItems(
    items: readonly WorldItemRecord[],
    onItemInteract: (item: WorldItemRecord) => void,
  ): void {
    const activeIds = new Set(items.map((item) => item.id));
    for (const [id, sprite] of this.worldItemSprites) {
      if (!activeIds.has(id)) {
        sprite.destroy();
        this.worldItemSprites.delete(id);
      }
    }

    for (const item of items) {
      const assetKey = item.item_id;
      if (!this.scene.textures.exists(assetKey)) continue;
      let sprite = this.worldItemSprites.get(item.id);
      if (sprite === undefined) {
        sprite = this.scene.add
          .image(item.x, item.y, assetKey)
          .setScale(0.5)
          .setInteractive({ useHandCursor: true });
        sprite.on('pointerdown', () => onItemInteract(item));
        this.worldItemSprites.set(item.id, sprite);
      }
      sprite.setPosition(item.x, item.y).setDepth(item.y + 5);
    }
  }

  destroy(): void {
    this.playerSprite?.destroy();
    for (const sprite of this.npcSprites) sprite.destroy();
    for (const sprite of this.worldItemSprites.values()) sprite.destroy();
    this.worldItemSprites.clear();
  }

  private ensurePlayerSprite(): void {
    if (this.playerSprite !== null) return;
    const { key, flipX } = this.resolveCharacterTexture(this.playerCharacterId, 'front');
    this.playerSprite = this.scene.add.image(0, 0, key).setDepth(10000);
    this.playerSprite.setFlipX(flipX);
    this.applyCharacterScale(this.playerCharacterId);
    this.scene.cameras.main.startFollow(this.playerSprite, true, 0.2, 0.2);
  }

  private resolveCharacterTexture(
    characterId: string,
    direction: string,
    isMoving = false,
    timeMs = 0,
  ): { key: string; flipX: boolean } {
    const cfg = CHARACTERS.find((character) => character.id === characterId) ?? CHARACTERS[0];
    const normalizedDirection = this.normalizeDirection(direction);
    const walkKey = cfg.states.walk[normalizedDirection];
    const standKey = cfg.states.stand[normalizedDirection];
    const fallback = cfg.states.stand['front'] ?? cfg.states.walk['front'];
    const resolvedWalkKey = this.resolveWalkFrame(walkKey, timeMs);
    const key =
      isMoving && resolvedWalkKey !== null
        ? resolvedWalkKey
        : typeof standKey === 'string'
          ? standKey
          : resolvedWalkKey !== null
            ? resolvedWalkKey
            : typeof fallback === 'string'
            ? fallback
            : Array.isArray(fallback)
              ? fallback[0]
              : String(fallback);
    const flipX =
      normalizedDirection === 'right' &&
      cfg.states.walk['right_mirror'] === true &&
      !Array.isArray(walkKey);
    return { key, flipX };
  }

  private resolveWalkFrame(walkKey: string | string[] | boolean | undefined, timeMs: number): string | null {
    if (typeof walkKey === 'string') return walkKey;
    if (!Array.isArray(walkKey) || walkKey.length === 0) return null;
    const frameIndex = Math.floor(timeMs / WALK_FRAME_MS) % walkKey.length;
    return walkKey[frameIndex];
  }

  private normalizeDirection(direction: string): string {
    if (direction === 'up' || direction === 'back') return 'back';
    if (direction === 'left') return 'left';
    if (direction === 'right') return 'right';
    return 'front';
  }

  private applyCharacterScale(characterId: string): void {
    if (this.playerSprite === null) return;
    const cfg = CHARACTERS.find((character) => character.id === characterId) ?? CHARACTERS[0];
    this.playerSprite.setScale(cfg.scale);
    this.playerSprite.setOrigin(cfg.anchor.x, cfg.anchor.y);
  }
}
