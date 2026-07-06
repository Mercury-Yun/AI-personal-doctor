import { createRouter, createWebHistory } from 'vue-router'
import { isMobileView, MOBILE_HIDDEN_ROUTES } from '../utils/mobileView'
import Dashboard from '../views/Dashboard.vue'
import FamilyHome from '../views/FamilyHome.vue'
import DoctorChat from '../views/DoctorChat.vue'
import HealthProfile from '../views/HealthProfile.vue'
import MedicationManager from '../views/MedicationManager.vue'
import MedicalRecord from '../views/MedicalRecord.vue'
import Reminder from '../views/Reminder.vue'
import DeviceStatus from '../views/DeviceStatus.vue'
import PhotoMedicine from '../views/PhotoMedicine.vue'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'Dashboard', component: Dashboard, meta: { title: '健康总览' } },
  { path: '/family', name: 'FamilyHome', component: FamilyHome, meta: { title: '家属守护' } },
  { path: '/doctor-chat', name: 'DoctorChat', component: DoctorChat, meta: { title: 'AI医生' } },
  { path: '/photo-medicine', name: 'PhotoMedicine', component: PhotoMedicine, meta: { title: '拍照问药' } },
  { path: '/profiles', name: 'HealthProfile', component: HealthProfile, meta: { title: '健康档案' } },
  { path: '/records', name: 'MedicalRecord', component: MedicalRecord, meta: { title: '病例管理' } },
  { path: '/medications', name: 'MedicationManager', component: MedicationManager, meta: { title: '药物管理' } },
  { path: '/reminders', name: 'Reminder', component: Reminder, meta: { title: '用药提醒' } },
  { path: '/device', name: 'DeviceStatus', component: DeviceStatus, meta: { title: '设备与语音' } }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  if (!isMobileView()) {
    // 看板（横屏）不使用家属端手机首页，回退到健康总览
    if (to.path === '/family') return '/dashboard'
    return true
  }
  // 手机窄屏进入家属守护首页
  if (to.path === '/dashboard') return '/family'
  if (MOBILE_HIDDEN_ROUTES.has(to.path)) {
    return '/profiles'
  }
  return true
})

export default router
