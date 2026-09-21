import type { SettingsRegistry } from "../types";
import { SettingsNav } from "../components/SettingsNav";
import { GenericSettingsLayout } from "../components/GenericSettingsLayout";
import { profileSettings } from "./registry";

export { SettingsNav, GenericSettingsLayout, profileSettings };
export { GeneralSection } from "./sections/GeneralSection";
export { NotificationsSection } from "./sections/NotificationsSection";
export { SecuritySection } from "./sections/SecuritySection";
export { ProfileSettingsLayout } from "./ProfileSettingsLayout";
export type { SettingsRegistry };
