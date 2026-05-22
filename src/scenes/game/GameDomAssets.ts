import assetsJson from '../../../config/assets.json';
import charactersJson from '../../../config/characters.json';
import itemsJson from '../../../config/items.json';

type AssetManifest = Record<string, string>;
const ASSETS = assetsJson as AssetManifest;

interface ItemMeta {
  id: string;
  asset_id: string;
}

interface CharacterMeta {
  id: string;
  states: { stand: Record<string, string | boolean> };
}

const ITEMS = itemsJson as ItemMeta[];
const CHARACTERS = charactersJson as CharacterMeta[];

export function itemImage(itemId: string): string {
  const meta = ITEMS.find((item) => item.id === itemId);
  return ASSETS[meta?.asset_id ?? itemId] ?? ASSETS[itemId] ?? '/assets/images/Items/item_magic_potion_1.png';
}

export function characterImage(characterId: string): string {
  const character = CHARACTERS.find((item) => item.id === characterId);
  const assetKey = character?.states.stand['front'];
  return typeof assetKey === 'string' ? ASSETS[assetKey] ?? '' : '';
}
