from __future__ import print_function
import os
import json
import visdom
import numpy as np
import torch
import torch.optim as optim
from torch.autograd import Variable
from scipy import sparse
import sys

sys.path.append("/content/drive/MyDrive/AAGWS-Wargame-master-master")
from util.util import plot_position, cvtFlatten2Offset
from util import util


class TrainSpatial(object):
    def __init__(self):
        pass

    @staticmethod
    def train(model, env, args):
        #################################### PLOT ###################################################
        save_pic_dir = os.path.join('../../data/result/{}'.format(args.name))
        if not os.path.isdir(save_pic_dir):
            os.makedirs(save_pic_dir)

        STEPS = 10
        LAMBDA = 0.95
        
        # vis = visdom.Visdom(env=args.name+'[{}]'.format(args.phrase))
        print("*****************************2")
        pre_per_replay = [[] for _ in range(args.n_replays)]
        gt_per_replay = [[] for _ in range(args.n_replays)]
        acc = None
        record_loss, record_loss_step, record_acc, record_acc_step = [], [], [], []
        print("**********************3")
        # win = vis.line(X=np.zeros(1), Y=np.zeros(1), name='action',)
        print("**********************4")
        # loss_win = vis.line(X=np.zeros(1), Y=np.zeros((1, 6)), name='action[TOTAL]',)

        print("************ TRAIN ************")
        torch.manual_seed(args.seed)
        torch.cuda.manual_seed(args.seed)

        gpu_id = args.gpu_id
        with torch.cuda.device(gpu_id):
            model = model.cuda() if gpu_id >= 0 else model
        model.train()
        optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=0.0001)

        epoch = 5
        save = args.save_intervel
        save_pic = int(args.save_intervel/2)
        env_return = env.step()
        if env_return is not None:
            (states_S, actions_gt), require_init, see_n_replays = env_return

        with torch.cuda.device(gpu_id):
            states_S = torch.from_numpy(states_S).float()
            actions_gt = torch.from_numpy(actions_gt).float()  #.squeeze()
            see_n_replays = torch.from_numpy(see_n_replays.astype(float)).float()
            if gpu_id >= 0:
                states_S = states_S.cuda()
                actions_gt = actions_gt.cuda()
                see_n_replays = see_n_replays.cuda()

        while True:
            actions = model(Variable(states_S))
            # print(actions.shape)
            action_loss = torch.sum((-actions_gt.view(args.n_replays, 6, -1) * (1e-6 + actions.view(args.n_replays, 6, -1)).log()), 2) * (1 - see_n_replays)
            # print(action_loss.shape)
            action_loss = action_loss.mean()
            # print(action_loss)
            model.zero_grad()
            action_loss.backward()
            optimizer.step()

            if env.epoch > epoch:
                # with open(os.path.join(args.save_path, 'config.json'), 'r') as f:
                #     old_args = json.load(f)
                #     old_args.lr = p['lr']
                #
                # with open(os.path.join(args.save_path, 'config.json'), 'w', encoding='utf-8') as file:
                #     json.dump(old_args, file, ensure_ascii=False)

                epoch = env.epoch
                for p in optimizer.param_groups:
                    p['lr'] *= 0.7
            ############################ PLOT ##########################################markers=True,
            # vis.line(X=np.asarray([env.step_count()]),
            #          Y=np.asarray([action_loss.data.cpu().numpy()]),
            #          win=loss_win,
            #          name='action',
            #          update='append')
            record_loss.append(action_loss.data.cpu().numpy().tolist())
            record_loss_step.append(env.step_count())
            actions_np = np.asarray([np.argmax(action.data.cpu().numpy().reshape(6, -1), axis=1) for action in actions])
            actions_gt_np = np.asarray([np.argmax(action_gt.cpu().numpy().reshape(6, -1), axis=1) for action_gt in actions_gt])

            for idx, (action, action_gt, init) in enumerate(zip(actions_np, actions_gt_np, require_init)):
                if init and len(pre_per_replay[idx]) > 0:
                    pre_per_replay[idx] = np.asarray(pre_per_replay[idx], dtype=np.uint16)
                    gt_per_replay[idx] = np.asarray(gt_per_replay[idx], dtype=np.uint16)
                    step = len(pre_per_replay[idx]) // STEPS
                    if step > 0:
                        acc_tmp = []
                        for s in range(STEPS):
                            action_np = pre_per_replay[idx][s * step:(s + 1) * step, :]
                            action_gt_np = gt_per_replay[idx][s * step:(s + 1) * step, :]
                            acc_tmp.append(np.mean(action_np == action_gt_np))

                        acc_tmp = np.asarray(acc_tmp)
                        if acc is None:
                            acc = acc_tmp
                        else:
                            acc = LAMBDA * acc + (1-LAMBDA) * acc_tmp

                        if acc is None:
                            continue
                    step = env.step_count()
                    acc_mean = np.mean(acc)
                    # for s in range(STEPS):
                    #     vis.line(X=np.asarray([step]),
                    #              Y=np.asarray([acc[s]]),
                    #              win=win,
                    #              name='{}[{}%~{}%]'.format('action', s * 10, (s + 1) * 10),
                    #              update='append')
                    # vis.line(X=np.asarray([env.step_count()]),
                    #          Y=np.asarray([acc_mean]),
                    #          win=win,
                    #          name='action[TOTAL]',
                    #          update='append')

                    record_acc.append(acc_mean)
                    record_acc_step.append(step)
                    if env.step_count() > save_pic:
                        save_pic = env.step_count() + int(args.save_intervel/2)
                        for num in range(6):

                            predict_position = [pos for pos in pre_per_replay[idx][:, num]]
                            true_position = [pos for pos in gt_per_replay[idx][:, num]]
                            map_dir = '../../data/map/城镇居民地.jpg'
                            plot_position(true_position, predict_position, map_dir, env.frame_size, save_pic_dir, str(env.step_count())+'-'+str(num))
                    pre_per_replay[idx] = []
                    gt_per_replay[idx] = []
            pre_per_replay[idx].append(action)
            gt_per_replay[idx].append(action_gt)
            ####################### NEXT BATCH ###################################
            env_return = env.step()
            if env_return is not None:
                (raw_states_S, raw_rewards), require_init, raw_see_n_replays = env_return
                # for i, states in enumerate(raw_states_S):
                #     for j, state in enumerate(states):
                #         util.plot_hot_map(state, str(i)+str(j))

                states_S = states_S.copy_(torch.from_numpy(raw_states_S).float())
                actions_gt = actions_gt.copy_(torch.from_numpy(raw_rewards).float())
                see_n_replays = see_n_replays.copy_(torch.from_numpy(raw_see_n_replays.astype(float)).float())
            if env.step_count() > save or env_return is None:
                save = env.step_count()+args.save_intervel
                torch.save(model.state_dict(),
                           os.path.join(args.model_path, 'model_iter_{}.pth'.format(env.step_count())))
                torch.save(model.state_dict(), os.path.join(args.model_path, 'model_latest.pth'))
            if env_return is None:
                env.close()
                break
        dic = {'record_loss': record_loss,
               'record_loss_step': record_loss_step,
               'record_acc': record_acc,
               'record_acc_step': record_acc_step}
        with open(os.path.join(args.save_path, 'loss.json'), 'w', encoding='utf-8') as json_file:
            json.dump(dic, json_file, ensure_ascii=False)

    @staticmethod
    def test(model, env, args):
        print("************** save result *************")
        save_pic_dir = os.path.join('../../data/result/test/{}'.format(args.name))
        if not os.path.isdir(save_pic_dir):
            os.makedirs(save_pic_dir)
        action_pre_per_replay = [[[]] for _ in range(6)]
        action_gt_per_replay = [[[]] for _ in range(6)]
        save_pic = 1000
        print("************** test *************")
        torch.manual_seed(args.seed)
        torch.cuda.manual_seed(args.seed)

        gpu_id = args.gpu_id
        with torch.cuda.device(gpu_id):
            model = model.cuda() if gpu_id >= 0 else model
        model.eval()

        env_return = env.step(test_mode=True)
        if env_return is not None:
            (states_S, actions_gt), require_init, see_n_replays = env_return
        with torch.cuda.device(gpu_id):
            states_S = torch.from_numpy(states_S).float()
            actions_gt = torch.from_numpy(actions_gt).float()
            # see_n_replays = torch.from_numpy(see_n_replays).float()
            if gpu_id >= 0:
                states_S = states_S.cuda()
                actions_gt = actions_gt.cuda()
                # see_n_replays = see_n_replays.cuda()
        while True:
            actions = model(Variable(states_S))
            print("************** plot *************")
            actions_np = np.asarray([np.argmax(action.data.cpu().numpy().reshape(6, -1), axis=1)
                                     for action in actions]).squeeze()
            actions_gt_np = np.asarray([np.argmax(action_gt.cpu().numpy().reshape(6, -1), axis=1)
                                        for action_gt in actions_gt]).squeeze()

            see_n_replays = see_n_replays.squeeze()

            if require_init[-1] and len(action_gt_per_replay[0][-1]) > 0:
                for piece in range(6):
                    action_pre_per_replay[piece][-1] = np.ravel(np.hstack(action_pre_per_replay[piece][-1]))
                    action_gt_per_replay[piece][-1] = np.ravel(np.hstack(action_gt_per_replay[piece][-1]))
                    action_pre_per_replay[piece].append([])
                    action_gt_per_replay[piece].append([])
                if env.step_count() > save_pic:
                    save_pic += save_pic + args.save_intervel/20
                    for piece in range(6):
                        predict_position = [pos for pos in action_pre_per_replay[piece][-2]]
                        true_position = [pos for pos in action_gt_per_replay[piece][-2]]
                        map_dir = '../../data/map/城镇居民地.jpg'
                        plot_position(true_position, predict_position, map_dir, env.frame_size, save_pic_dir, str(env.step_count()) + '-' + str(piece))
            for piece in range(6):
                if not see_n_replays[piece]:
                    action_pre_per_replay[piece][-1].append(actions_np[piece])
                    action_gt_per_replay[piece][-1].append(actions_gt_np[piece])

            print("************** next batch *************")
            env_return = env.step(test_mode=True)
            if env_return is not None:
                (raw_states_S, raw_actions), require_init, see_n_replays = env_return
                states_S = states_S.copy_(torch.from_numpy(raw_states_S).float())
                actions_gt = actions_gt.copy_(torch.from_numpy(raw_actions).float())
            else:
                for piece in range(6):
                    action_pre_per_replay[piece][-1] = np.ravel(np.hstack(action_pre_per_replay[piece][-1]))
                    action_gt_per_replay[piece][-1] = np.ravel(np.hstack(action_gt_per_replay[piece][-1]))

                env.close()
                break

        return action_pre_per_replay, action_gt_per_replay


    @staticmethod
    def test_pro(model, env, args):
        ######################### SAVE RESULT ############################
        save_pic_dir = os.path.join('../../data/result/test_pro/{}'.format(args.name))
        pic_num = 10
        if not os.path.isdir(save_pic_dir):
            os.makedirs(save_pic_dir)
        action_pre_per_replay = [[[]] for _ in range(6)]
        action_gt_per_replay = [[[]] for _ in range(6)]
        ######################### TEST ###################################
        torch.manual_seed(args.seed)
        torch.cuda.manual_seed(args.seed)

        gpu_id = args.gpu_id
        with torch.cuda.device(gpu_id):
            model = model.cuda() if gpu_id >= 0 else model
        model.eval()

        env_return = env.step(test_mode=True)
        if env_return is not None:
            (states_S, actions_gt), require_init, see_n_replays = env_return
        with torch.cuda.device(gpu_id):
            states_S = torch.from_numpy(states_S).float()
            actions_gt = torch.from_numpy(actions_gt).float()
            if gpu_id >= 0:
                states_S = states_S.cuda()
                actions_gt = actions_gt.cuda()

        while True:
            actions = model(Variable(states_S))
            ############################ PLOT ##########################################
            actions_np = np.asarray([np.argsort(action.data.cpu().numpy().reshape(6, -1), axis=1)
                                     for action in actions]).squeeze()
            actions_np = actions_np[:, -50:]

            actions_gt_np = np.asarray([np.argmax(action_gt.cpu().numpy().reshape(6, -1), axis=1)
                                        for action_gt in actions_gt]).squeeze()

            see_n_replays = see_n_replays.squeeze()

            if require_init[-1] and len(action_gt_per_replay[0][-1]) > 0:
                for piece in range(6):
                    action_pre_per_replay[piece][-1] = np.vstack(action_pre_per_replay[piece][-1]).squeeze()
                    action_gt_per_replay[piece][-1] = np.hstack(action_gt_per_replay[piece][-1]).squeeze()
                    # print(action_pre_per_replay[piece][-1].shape, action_gt_per_replay[piece][-1].shape)
                    action_pre_per_replay[piece].append([])
                    action_gt_per_replay[piece].append([])
                pic_num -= 1
                if pic_num > 0 :
                    for piece in range(6):
                        predict_position = [pos for pos in action_pre_per_replay[piece][-2][:, -1]]
                        true_position = [pos for pos in action_gt_per_replay[piece][-2]]
                        map_dir = '../../data/map/城镇居民地.jpg'
                        plot_position(true_position, predict_position, map_dir, env.frame_size, save_pic_dir, str(env.step_count()) + '-' + str(piece))
            for piece in range(6):
                if not see_n_replays[piece]:
                    action_pre_per_replay[piece][-1].append(actions_np[piece, :])
                    action_gt_per_replay[piece][-1].append(actions_gt_np[piece])

            ########################### NEXT BATCH #############################################
            env_return = env.step(test_mode=True)
            if env_return is not None:
                (raw_states_S, raw_actions), require_init, see_n_replays = env_return
                states_S = states_S.copy_(torch.from_numpy(raw_states_S).float())
                actions_gt = actions_gt.copy_(torch.from_numpy(raw_actions).float())
            else:
                for piece in range(6):
                    action_pre_per_replay[piece][-1] = np.vstack(action_pre_per_replay[piece][-1]).squeeze()
                    action_gt_per_replay[piece][-1] = np.hstack(action_gt_per_replay[piece][-1]).squeeze()

                env.close()
                break

        return action_pre_per_replay, action_gt_per_replay

    @staticmethod
    def predect(model, env, args):


        torch.manual_seed(args.seed)
        torch.cuda.manual_seed(args.seed)

        gpu_id = args.gpu_id
        with torch.cuda.device(gpu_id):
            model = model.cuda() if gpu_id >= 0 else model
        model.eval()

        env_return = env.step(test_mode=True)
        if env_return is not None:
            ((states_S, actions_gt), all_feature), require_init, see_n_replays = env_return
            S = np.asarray(all_feature.S).squeeze()
            G = np.asarray(all_feature.G).squeeze()
            A = np.asarray(all_feature.A).squeeze()
        with torch.cuda.device(gpu_id):
            states_S = torch.from_numpy(states_S).float()
            # actions_gt_torch = torch.from_numpy(actions_gt).float()
            if gpu_id >= 0:
                states_S = states_S.cuda()
                # actions_gt_torch = actions_gt_torch.cuda()
        states_tensor = []
        states_vector = []
        acts = []
        while True:
            actions = model(Variable(states_S))
            ############################ PLOT ##########################################
            actions_np = np.asarray([action.data.cpu().numpy().reshape(6, env.frame_size[0], env.frame_size[1])
                                     for action in actions]).squeeze()

            see_n_replays = see_n_replays.squeeze()
            # print(see_n_replays)
            for i, see_not in enumerate(see_n_replays):
                if not see_not:
                    S[7 + i, :, :] = actions_np[i, :, :]


            if require_init[-1] and len(states_tensor) > 0:
                spatial_states_np = np.concatenate(states_tensor).reshape([len(states_vector), -1])
                vector_states_np = np.vstack(states_vector)
                acts_np = np.vstack(acts)
                states_tensor = []
                states_vector = []
                acts = []
                print(spatial_states_np.shape, vector_states_np.shape, acts_np.shape)
                sparse.save_npz(os.path.join(args.save_data_path, path[0].split('/')[-1][:-4]), sparse.csr_matrix(spatial_states_np))
                sparse.save_npz(os.path.join(args.save_data_path, path[1].split('/')[-1][:-4]), sparse.csr_matrix(vector_states_np))
                sparse.save_npz(os.path.join(args.save_data_path, path[2].split('/')[-1][:-4]), sparse.csr_matrix(acts_np))


            states_tensor.append(S)
            states_vector.append(G)
            acts.append(A)
            path = env.path
            #
            # ########################### NEXT BATCH #############################################
            env_return = env.step(test_mode=True)
            if env_return is not None:
                ((raw_states_S, raw_actions), all_feature),require_init, see_n_replays = env_return
                S = np.asarray(all_feature.S).squeeze()
                G = np.asarray(all_feature.G).squeeze()
                A = np.asarray(all_feature.A).squeeze()
                states_S = states_S.copy_(torch.from_numpy(raw_states_S).float())
                # actions_gt = actions_gt.copy_(torch.from_numpy(raw_actions).float())
            else:

                spatial_states_np = np.concatenate(states_tensor).reshape([len(states_vector), -1])
                vector_states_np = np.vstack(states_vector)
                acts_np = np.vstack(acts)
                sparse.save_npz(os.path.join(args.save_data_path, path[0].split('/')[-1][:-4]),
                                sparse.csr_matrix(spatial_states_np))
                sparse.save_npz(os.path.join(args.save_data_path, path[1].split('/')[-1][:-4]),
                                sparse.csr_matrix(vector_states_np))
                sparse.save_npz(os.path.join(args.save_data_path, path[2].split('/')[-1][:-4]),
                                sparse.csr_matrix(acts_np))

                env.close()
                break

        return True