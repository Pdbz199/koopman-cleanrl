import gym
import matplotlib.pyplot as plt
import numpy as np
import os
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F

from torch.distributions import Normal

#%% Set seed for reproducibility
seed = 123
np.random.seed(seed)
torch.manual_seed(seed)

#%% Variables
state_size = 3
action_size = 1

#%% Dynamics
A = np.zeros([state_size, state_size])
max_abs_real_eigen_val = 1.0
while max_abs_real_eigen_val >= 1.0 or max_abs_real_eigen_val <= 0.7:
    Z = np.random.rand(*A.shape)
    _,sigma,__ = np.linalg.svd(Z)
    Z /= np.max(sigma)
    A = Z.T @ Z
    W,_ = np.linalg.eig(A)
    max_abs_real_eigen_val = np.max(np.abs(np.real(W)))

print("A:", A)
print("A's max absolute real eigenvalue:", max_abs_real_eigen_val)
B = np.ones([state_size,action_size])

def f(x, u):
    return A @ x + B @ u

#%% Define cost
# Q = np.eye(state_size)
Q = torch.eye(state_size)
R = 1
w_r = torch.Tensor([
    [0.0],
    [0.0],
    [0.0]
])
# def cost(x, u):
#     # Assuming that data matrices are passed in for X and U. Columns are snapshots
#     # x.T Q x + u.T R u
#     x_ = x - w_r
#     mat = np.vstack(np.diag(x_.T @ Q @ x_)) + np.power(u, 2)*R
#     return mat.T
def cost(x, u):
    _x = x - w_r
    return _x.T @ Q @ _x + u * R * u

""""""""""""""""""""""""""" SOFT ACTOR CRITIC IMPLEMENTATION """""""""""""""""""""""""""

class ReplayBuffer():
    def __init__(self, max_size, input_shape, num_actions):
        self.memory_size = max_size
        self.memory_counter = 0
        self.state_memory = np.zeros([self.memory_size, *input_shape])
        self.new_state_memory = np.zeros([self.memory_size, *input_shape])
        self.action_memory = np.zeros([self.memory_size, num_actions])
        self.reward_memory = np.zeros([self.memory_size])
        self.terminal_memory = np.zeros(self.memory_size, dtype=bool)

    def store_transition(self, state, action, reward, state_, done):
        index = self.memory_counter % self.memory_size

        self.state_memory[index] = state
        self.action_memory[index] = action
        self.reward_memory[index] = reward
        self.new_state_memory[index] = state_
        self.terminal_memory[index] = done

        self.memory_counter += 1

    def sample_buffer(self, batch_size):
        max_mem = min(self.memory_counter, self.memory_size)

        batch_indices = np.random.choice(max_mem, batch_size)

        states = self.state_memory[batch_indices]
        states_ = self.new_state_memory[batch_indices]
        actions = self.action_memory[batch_indices]
        rewards = self.reward_memory[batch_indices]
        dones = self.terminal_memory[batch_indices]

        return states, states_, actions, rewards, dones

class CriticNetwork(nn.Module):
    def __init__(self, beta, input_dimensions, num_actions, fc1_dimensions=256, fc2_dimensions=256, name='critic', checkpoint_directory='tmp/sac'):
        super(CriticNetwork, self).__init__()

        self.input_dimensions = input_dimensions
        self.num_actions = num_actions
        self.name = name
        self.fc1_dimensions = fc1_dimensions
        self.fc2_dimensions = fc2_dimensions
        self.checkpoint_directory = checkpoint_directory
        self.checkpoint_file = os.path.join(self.checkpoint_directory, self.name+'_sac')

        self.fc1 = nn.Linear(self.input_dimensions[0] + self.num_actions, self.fc1_dimensions)
        self.fc2 = nn.Linear(self.fc1_dimensions, self.fc2_dimensions)
        self.q = nn.Linear(self.fc2_dimensions, 1)

        self.optimizer = optim.Adam(self.parameters(), lr=beta)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.to(self.device)

    def forward(self, state, action):
        action_value = self.fc1(torch.cat([state, action], dim=1))
        action_value = F.relu(action_value)
        action_value = self.fc2(action_value)
        action_value = F.relu(action_value)

        q = self.q(action_value)

        return q

    def save_checkpoint(self):
        # torch.save(self.state_dict(), self.checkpoint_file)
        pass

    def load_checkpoint(self):
        self.load_state_dict(torch.load(self.checkpoint_file))

class ValueNetwork(nn.Module):
    def __init__(self, beta, input_dimensions, fc1_dimensions=256, fc2_dimensions=256, name='value', checkpoint_directory='tmp/sac'):
        super(ValueNetwork, self).__init__()

        self.input_dimensions = input_dimensions
        self.fc1_dimensions = fc1_dimensions
        self.fc2_dimensions = fc2_dimensions
        self.name = name
        self.checkpoint_directory = checkpoint_directory
        self.checkpoint_file = os.path.join(self.checkpoint_directory, self.name+'_sac')

        self.fc1 = nn.Linear(*self.input_dimensions, self.fc1_dimensions)
        self.fc2 = nn.Linear(self.fc1_dimensions, self.fc2_dimensions)
        self.v = nn.Linear(self.fc2_dimensions, 1)

        self.optimizer = optim.Adam(self.parameters(), lr=beta)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.to(self.device)

    def forward(self, state):
        state_value = self.fc1(state)
        state_value = F.relu(state_value)
        state_value = self.fc2(state_value)
        state_value = F.relu(state_value)

        v = self.v(state_value)

        return v

    def save_checkpoint(self):
        torch.save(self.state_dict(), self.checkpoint_file)

    def load_checkpoint(self):
        self.load_state_dict(torch.load(self.checkpoint_file))

class ActorNetwork(nn.Module):
    def __init__(self, alpha, input_dimensions, max_action, num_actions=2, fc1_dimensions=256, fc2_dimensions=256, name='actor', checkpoint_directory='tmp/sac'):
        super(ActorNetwork, self).__init__()

        self.input_dimensions = input_dimensions
        self.max_action = max_action
        self.num_actions = num_actions
        self.fc1_dimensions = fc1_dimensions
        self.fc2_dimensions = fc2_dimensions
        self.reparam_noise = 1e-6
        self.name = name
        self.checkpoint_directory = checkpoint_directory
        self.checkpoint_file = os.path.join(self.checkpoint_directory, self.name+'_sac')

        self.fc1 = nn.Linear(*self.input_dimensions, self.fc1_dimensions)
        self.fc2 = nn.Linear(self.fc1_dimensions, self.fc2_dimensions)
        self.mu = nn.Linear(self.fc2_dimensions, self.num_actions)
        self.sigma = nn.Linear(self.fc2_dimensions, self.num_actions)

        self.optimizer = optim.Adam(self.parameters(), lr=alpha)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.to(self.device)

    def forward(self, state):
        prob = self.fc1(state)
        prob = F.relu(prob)
        prob = self.fc2(prob)
        prob = F.relu(prob)

        mu = self.mu(prob)
        sigma = self.sigma(prob)

        sigma = torch.clamp(sigma, min=self.reparam_noise, max=1)

        return mu, sigma

    def sample_normal(self, state, reparameterize=True):
        mu, sigma = self(state)
        probabilities = Normal(mu, sigma)

        if reparameterize:
            actions = probabilities.rsample()
        else:
            actions = probabilities.sample()

        action = torch.tanh(actions) * torch.tensor(self.max_action).to(self.device)
        log_probs = probabilities.log_prob(actions)
        log_probs -= torch.log(1 - action.pow(2) + self.reparam_noise)
        log_probs = log_probs.sum(-1, keepdim=True)

        return action, log_probs

    def save_checkpoint(self):
        torch.save(self.state_dict(), self.checkpoint_file)

    def load_checkpoint(self):
        self.load_state_dict(torch.load(self.checkpoint_file))

class Agent():
    def __init__(self, max_action, alpha=0.0003, beta=0.0003, input_dimensions=[8], env=None, gamma=0.99, num_actions=2, max_size=1_000_000, tau=0.005, layer1_size=256, layer2_size=256, batch_size=256, reward_scale=2):
        self.gamma = gamma
        self.tau = tau
        self.memory = ReplayBuffer(max_size, input_dimensions, num_actions)
        self.batch_size = batch_size
        self.num_actions = num_actions

        self.actor = ActorNetwork(alpha, input_dimensions, max_action=max_action, num_actions=num_actions)
        self.critic_1 = CriticNetwork(beta, input_dimensions, num_actions, name='critic_1')
        self.critic_2 = CriticNetwork(beta, input_dimensions, num_actions, name='critic_2')
        self.value = ValueNetwork(beta, input_dimensions)
        self.target_value = ValueNetwork(beta, input_dimensions, name='target_value')

        self.scale = reward_scale
        self.update_network_parameters(tau=1)

    def choose_action(self, observation):
        state = torch.Tensor(observation).to(self.actor.device)
        actions, _ = self.actor.sample_normal(state, reparameterize=False)

        return actions.cpu().detach().numpy()[0]

    def remember(self, state, action, reward, new_state, done):
        self.memory.store_transition(state, action, reward, new_state, done)

    def update_network_parameters(self, tau=None):
        if tau is None:
            tau = self.tau

        target_value_params = self.target_value.named_parameters()
        value_params = self.value.named_parameters()

        target_value_state_dict = dict(target_value_params)
        value_state_dict = dict(value_params)

        for name in value_state_dict:
            value_state_dict[name] = tau*value_state_dict[name].clone() + \
                    (1-tau)*target_value_state_dict[name].clone()

            self.target_value.load_state_dict(value_state_dict)

    def save_models(self):
        print('..... saving models .....')
        self.actor.save_checkpoint()
        self.value.save_checkpoint()
        self.target_value.save_checkpoint()
        self.critic_1.save_checkpoint()
        self.critic_2.save_checkpoint()

    def load_models(self):
        print('..... loading models .....')
        self.actor.load_checkpoint()
        self.value.load_checkpoint()
        self.target_value.load_checkpoint()
        self.critic_1.load_checkpoint()
        self.critic_2.load_checkpoint()

    def learn(self):
        if self.memory.memory_counter < self.batch_size:
            return

        state, new_state, action, reward, done = \
                self.memory.sample_buffer(self.batch_size)

        state = torch.tensor(state, dtype=torch.float).to(self.actor.device)
        action = torch.tensor(action, dtype=torch.float).to(self.actor.device)
        reward = torch.tensor(reward, dtype=torch.float).to(self.actor.device)
        done = torch.tensor(done).to(self.actor.device)
        state_ = torch.tensor(new_state, dtype=torch.float).to(self.actor.device)

        value = self.value(state)#.view(-1)
        value_ = self.target_value(state_)#.view(-1)
        value_[done] = 0.0

        actions, log_probs = self.actor.sample_normal(state, reparameterize=False)
        # log_probs = log_probs.view(-1)
        q1_new_policy = self.critic_1(state, actions)
        q2_new_policy = self.critic_2(state, actions)
        critic_value = torch.min(q1_new_policy, q2_new_policy)
        # critic_value = critic_value.view(-1)

        value_target = critic_value - log_probs
        value_loss = 0.5 * F.mse_loss(value, value_target)
        self.value.optimizer.zero_grad()
        value_loss.backward(retain_graph=True)
        self.value.optimizer.step()

        actions, log_probs = self.actor.sample_normal(state, reparameterize=True)
        # log_probs = log_probs.view(-1)
        q1_new_policy = self.critic_1(state, actions)
        q2_new_policy = self.critic_2(state, actions)
        critic_value = torch.min(q1_new_policy, q2_new_policy)
        # critic_value = critic_value.view(-1)

        actor_loss = log_probs - critic_value
        actor_loss = torch.mean(actor_loss)
        self.actor.optimizer.zero_grad()
        actor_loss.backward(retain_graph=True)
        self.actor.optimizer.step()

        q_hat = self.scale*reward + self.gamma*value_
        q1_old_policy = self.critic_1(state, action)#.view(-1)
        q2_old_policy = self.critic_2(state, action)#.view(-1)
        critic_1_loss = 0.5 * F.mse_loss(q1_old_policy, q_hat)
        critic_2_loss = 0.5 * F.mse_loss(q2_old_policy, q_hat)
        critic_loss = critic_1_loss + critic_2_loss
        self.critic_1.optimizer.zero_grad()
        self.critic_2.optimizer.zero_grad()
        critic_loss.backward()
        self.critic_1.optimizer.step()
        self.critic_2.optimizer.step()

        self.update_network_parameters()

def plot_learning_curve(x, scores, figure_file):
    running_avg = np.zeros(len(scores))
    for i in range(len(running_avg)):
        running_avg[i] = np.mean(scores[max(0, i-100):(i+1)])
    plt.plot(x, running_avg)
    plt.title('Running average of previous 100 scores')
    plt.savefig(figure_file)

if __name__ == '__main__':
    agent = Agent(input_dimensions=[state_size], max_action=25, num_actions=1, batch_size=1)
    num_games = 150
    # num_games = 0

    filename = 'lqr-continuous-sac.png'
    figure_file = 'plots/' + filename

    # best_score = env.reward_range[0]
    best_score = -10_000_000
    score_history = []
    load_checkpoint = False
    # load_checkpoint = True

    if load_checkpoint:
        agent.load_models()
        # env.render(mode='human')

    # state_range = 25.0
    state_range = 5.0
    state_minimums = np.ones([state_size,1]) * -state_range
    state_maximums = np.ones([state_size,1]) * state_range

    initial_states = np.random.uniform(
        state_minimums,
        state_maximums,
        [state_size, num_games]
    )

    for game in range(num_games):
        # observation = env.reset()
        observation = initial_states[:,game]
        done = False
        score = 0
        # for step in range(200):
        while not done:
            action = np.array([[agent.choose_action(observation)]])

            # observation_, reward, done, info = env.step(action)

            observation_ = f(
                np.vstack(observation),
                action
            )[:,0]

            reward = -cost(
                torch.Tensor(np.vstack(observation)),
                torch.Tensor(action)
            )[0,0]

            score += reward

            done = np.linalg.norm(observation) >= 1000

            agent.remember(observation, action, reward, observation_, done)

            if not load_checkpoint:
                agent.learn()

            observation = observation_

        score_history.append(score)
        avg_score = np.mean(score_history[-100:])

        if avg_score > best_score:
            best_score = avg_score
            if not load_checkpoint:
                agent.save_models()

        print(f"episode {game}, score {score}, avg_score {avg_score}")

    if not load_checkpoint:
        x = [i+1 for i in range(num_games)]
        plot_learning_curve(x, score_history, figure_file)