import numpy as np
import torch
import torch.nn as nn

import sys
sys.path.append('../')
from tensor import KoopmanTensor, OLS

class DiscreteKoopmanActorCriticPolicy:
    """
        Compute the optimal policy for the given state using discrete Koopman actor critic methodology.
    """

    def __init__(
        self,
        true_dynamics,
        gamma,
        dynamics_model: KoopmanTensor,
        state_minimums,
        state_maximums,
        all_actions,
        cost,
        saved_file_path,
        dt=1.0,
        learning_rate=0.0003,
        w_hat_batch_size=2**12,
        seed=123,
        load_model=False
    ):
        """
            Constructor for the DiscreteKoopmanPolicyIterationPolicy class.

            INPUTS:
                true_dynamics: The true dynamics of the system.
                gamma: The discount factor of the system.
                dynamics_model: The Koopman tensor of the system.
                state_minimums: The minimum values of the state. Should be a column vector.
                state_maximums: The maximum values of the state. Should be a column vector.
                all_actions: The actions that the policy can take. Should be a single dimensional array.
                cost: The cost function of the system. Function must take in states and actions and return scalars.
                saved_file_path: The path to save the policy model.
                dt: The time step of the system.
                learning_rate: The learning rate of the policy.
                w_hat_batch_size: The batch size of the policy.
        """

        self.seed = seed
        torch.manual_seed(self.seed)
        np.random.seed(self.seed)

        self.true_dynamics = true_dynamics
        self.gamma = gamma
        self.dynamics_model = dynamics_model
        self.phi = self.dynamics_model.phi
        self.psi = self.dynamics_model.psi
        self.state_minimums = state_minimums
        self.state_maximums = state_maximums
        self.all_actions = all_actions
        self.cost = cost
        self.saved_file_path = saved_file_path
        split_path = self.saved_file_path.split('.')
        if len(split_path) == 1:
            self.saved_file_path_w_hat = split_path[0] + '-w_hat.pt'
        else:
            self.saved_file_path_w_hat = split_path[0] + '-w_hat.' + split_path[1]
        self.dt = dt
        self.learning_rate = learning_rate
        self.w_hat_batch_size = w_hat_batch_size

        if load_model:
            self.policy_model = torch.load(self.saved_file_path) # actor model
            self.w_hat = torch.load(self.saved_file_path_w_hat).numpy()  # critic weights
        else:
            self.policy_model = nn.Sequential(
                nn.Linear(self.dynamics_model.x_dim, self.all_actions.shape[0]),
                nn.Softmax(dim=-1)
            ) # actor model

            # self.policy_model = nn.Sequential(
            #     nn.Linear(self.dynamics_model.phi_dim, self.all_actions.shape[0]),
            #     nn.Softmax(dim=-1)
            # ) # actor model

            self.w_hat = np.zeros(self.dynamics_model.phi_column_dim) # critic weights

            # self.critic_model = nn.Sequential(
            #     nn.Linear(self.dynamics_model.x_dim, 128),
            #     nn.ReLU(),
            #     nn.Linear(128, 256),
            #     nn.ReLU(),
            #     nn.Linear(256, 1)
            # )

            def init_weights(m):
                if type(m) == torch.nn.Linear:
                    m.weight.data.fill_(0.0)

            self.policy_model.apply(init_weights)
            # self.critic_model.apply(init_weights)

        self.optimizer = torch.optim.Adam(self.policy_model.parameters(), self.learning_rate)
        # self.critic_optimizer = torch.optim.Adam(self.critic_model.parameters(), self.learning_rate)

    def update_w_hat(self):
        x_batch_indices = np.random.choice(self.dynamics_model.X.shape[1], self.w_hat_batch_size, replace=False)
        x_batch = self.dynamics_model.X[:, x_batch_indices] # (state_dim, w_hat_batch_size)
        phi_x_batch = self.dynamics_model.phi(x_batch) # (phi_dim, w_hat_batch_size)

        with torch.no_grad():
            pi_response = self.policy_model(torch.Tensor(x_batch.T)).T # (all_actions.shape[0], w_hat_batch_size)

        phi_x_prime_batch = self.dynamics_model.K_(np.array([self.all_actions])) @ phi_x_batch # (all_actions.shape[0], phi_dim, w_hat_batch_size)
        phi_x_prime_batch_prob = np.einsum('upw,uw->upw', phi_x_prime_batch, pi_response.data.numpy()) # (all_actions.shape[0], phi_dim, w_hat_batch_size)
        expectation_term_1 = np.sum(phi_x_prime_batch_prob, axis=0) # (phi_dim, w_hat_batch_size)

        reward_batch_prob = np.einsum(
            'uw,uw->wu',
            -self.cost(x_batch, np.array([self.all_actions])),
            pi_response.data.numpy()
        ) # (w_hat_batch_size, all_actions.shape[0])
        expectation_term_2 = np.array([
            np.sum(reward_batch_prob, axis=1) # (w_hat_batch_size,)
        ]) # (1, w_hat_batch_size)

        self.w_hat = OLS(
            (phi_x_batch - ((self.gamma**self.dt)*expectation_term_1)).T,
            expectation_term_2.T
        )

    def get_action(self, s):
        """
            INPUTS:
                s - 1D state array    
        """
        action_probs = self.policy_model(torch.Tensor(s))
        action_index = np.random.choice(self.all_actions.shape[0], p=np.squeeze(action_probs.detach().numpy()))
        action = self.all_actions[action_index]
        return action

    def actor_critic(
        self,
        num_training_episodes,
        num_steps_per_episode
    ):
        """
            REINFORCE algorithm
                
            INPUTS:
                num_training_episodes: number of episodes to train for
                num_steps_per_episode: number of steps per episode
        """

        # Initialize R_bar (Average reward)
        # R_bar = 0.0

        # Initialize S
        initial_states = np.random.uniform(
            self.state_minimums,
            self.state_maximums,
            [self.dynamics_model.x_dim, num_training_episodes]
        )
        total_reward_episode = torch.zeros(num_training_episodes)

        for episode in range(num_training_episodes):
            states = []
            action_probs_history = []
            critic_value_history = []
            rewards_history = []
            running_reward = 0
            episode_reward = 0

            state = np.vstack(initial_states[:, episode])
            for step in range(num_steps_per_episode):
                # Add newest state to list of previous states
                states.append(torch.Tensor(state)[:,0])

                # Get action probabilities and action for current state
                action_probs = self.policy_model(torch.Tensor(state.T))
                action_index = np.random.choice(self.all_actions.shape[0], p=np.squeeze(action_probs.detach().numpy()))
                action = self.all_actions[action_index]
                action_probs_history.append(torch.log(action_probs[:,action_index]))

                # Compute V_x
                V_x = torch.Tensor(self.w_hat.T @ self.phi(np.vstack(state)))
                critic_value_history.append(V_x)

                # Take action A, observe S', R
                next_state = self.true_dynamics(state, np.array([[action]]))
                curr_reward = -self.cost(state, action)[0,0]

                total_reward_episode[episode] += (self.gamma**(step*self.dt)) * curr_reward
                # total_reward_episode[episode] += self.gamma**step * curr_reward

                rewards_history.append(curr_reward)
                episode_reward += curr_reward

                # Update state for next loop
                state = next_state

            # Update running reward to check condition for solving
            running_reward = 0.05 * episode_reward + (1 - 0.05) * running_reward

            # Calculate expected value from rewards
            # - At each timestep what was the total reward received after that timestep
            # - Rewards in the past are discounted by multiplying them with gamma
            # - These are the labels for our critic
            returns = []
            discounted_sum = 0
            for r in rewards_history[::-1]:
                discounted_sum = r + self.gamma * discounted_sum
                returns.insert(0, discounted_sum)

            # Normalize
            eps = np.finfo(np.float32).eps.item()
            returns = np.array(returns)
            returns = (returns - np.mean(returns)) / (np.std(returns) + eps)
            returns = returns.tolist()

            # Calculating loss values to update our network
            actor_losses = []
            critic_losses = []
            for log_prob, value, ret in zip(action_probs_history, critic_value_history, returns):
                # At this point in history, the critic estimated that we would get a
                # total reward = `value` in the future. We took an action with log probability
                # of `log_prob` and ended up receiving a total reward = `ret`.
                # The actor must be updated so that it predicts an action that leads to
                # high rewards (compared to critic's estimate) with high probability.
                diff = ret - value
                actor_losses.append(-log_prob * diff)  # actor loss

                # The critic must be updated so that it predicts a better estimate of the future rewards
                critic_losses.append(torch.pow(ret - value, 2))

            # Compute loss
            loss_value = sum(actor_losses) + sum(critic_losses)

            # Backpropagation
            self.optimizer.zero_grad()
            loss_value.backward()
            self.optimizer.step()

            # OLS for w_hat
            self.update_w_hat()

            # Clear the loss and reward history
            action_probs_history.clear()
            critic_value_history.clear()
            rewards_history.clear()

            if (episode+1) % 250 == 0:
                print(f"Episode: {episode+1}, discounted total reward: {total_reward_episode[episode]}")
                torch.save(self.policy_model, self.saved_file_path)
                torch.save(torch.Tensor(self.w_hat), self.saved_file_path_w_hat)